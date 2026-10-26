"""WebSocket endpoint: microphone audio in, transcribed text out.

    WS /ws/transcribe/{meeting_code}?token=<jwt>

WHY THIS EXISTS ALONGSIDE THE WEB SPEECH API
--------------------------------------------
The browser's Web Speech API is faster, streams word by word, and costs us
nothing — it is the default for good reasons. It is also Chromium-only, and in
Chrome it sends the audio to Google's servers. This endpoint is the answer to
both problems: it runs Whisper on our own machine, so it works in Firefox and
Safari, and the audio never leaves the network the backend is on.

WHAT CROSSES THIS SOCKET, AND WHY IT IS A DIFFERENT SOCKET
----------------------------------------------------------
Audio. This is the ONLY socket in BridgeTalk that carries media, and it exists
only while the Whisper provider is selected.

It is deliberately separate from `/ws/predict`:
  * that socket carries landmark coordinates and never media, which is a
    privacy claim the code should keep obviously true;
  * a failure here — a missing model, a slow transcription — must not take
    sign recognition down with it;
  * the message contracts have nothing in common.

Recognised captions are NOT returned to the meeting from here. They go back to
the browser, which relays them over the existing inference socket exactly as
Web Speech results do, so both providers reach the other participant by one
path and the transcript sees one kind of event.

HOW AN UTTERANCE IS FOUND
-------------------------
Whisper transcribes a finished chunk of speech; it has no notion of streaming.
So the server buffers incoming audio and decides where a sentence ends using
simple energy-based voice activity detection: when the recent audio is quiet
for long enough, whatever came before it is one utterance and gets transcribed.

That is cruder than a trained VAD and is the right trade here — it costs no
extra model, no extra dependency, and no GPU, and the failure mode is a
sentence split in two rather than a wrong transcription.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

import numpy as np
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.config import settings
from app.core.security import decode_access_token
from app.database import SessionLocal
from app.models.user import User

logger = logging.getLogger("bridgetalk.ws.transcribe")

router = APIRouter()

WS_POLICY_VIOLATION = 1008
WS_INTERNAL_ERROR = 1011

# Whisper wants 16 kHz mono float32. Everything below is in those units.
SAMPLE_RATE = 16_000

# Root-mean-square below this counts as silence. Chosen against real microphone
# input with echo cancellation on, where the noise floor sits near 0.005.
SILENCE_RMS = 0.015

# Quiet for this long ends an utterance. Shorter and it cuts people off
# mid-sentence at natural pauses; longer and captions feel laggy.
SILENCE_DURATION_S = 0.7

# An utterance shorter than this is almost always a cough, a door, or the
# start of a word clipped by the silence detector. Transcribing it wastes a
# model call and usually produces a hallucinated word.
MIN_UTTERANCE_S = 0.4

# Hard ceiling so one person talking continuously still produces captions
# rather than an ever-growing buffer that is never transcribed.
MAX_UTTERANCE_S = 12.0


class WhisperTranscriber:
    """Loads faster-whisper once and transcribes utterances.

    Deliberately tolerant of the model being absent: this is a fallback
    provider, and a deployment that only ever uses Web Speech should still
    start cleanly. The socket reports MODEL_NOT_LOADED rather than the backend
    refusing to boot.
    """

    def __init__(self) -> None:
        self._model: Any = None
        self.load_error: Optional[str] = None
        self.model_size: str = settings.whisper_model_size

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def load(self) -> bool:
        """Load the model. Never raises; returns success."""
        try:
            # Imported lazily and inside the try, so a backend without
            # faster-whisper installed still starts and simply reports that
            # this provider is unavailable.
            from faster_whisper import WhisperModel
        except ImportError:
            self.load_error = (
                "faster-whisper is not installed. "
                "Install it with: pip install -r backend/requirements.txt"
            )
            logger.info("Whisper unavailable — %s", self.load_error)
            return False

        try:
            started = time.perf_counter()
            self._model = WhisperModel(
                self.model_size,
                device="cpu",
                # int8 rather than float32: roughly 4x less memory and
                # noticeably faster on CPU, for a negligible accuracy cost at
                # this model size. The whole project is CPU-only by constraint.
                compute_type="int8",
                download_root=str(settings.resolve_path(settings.whisper_cache_dir)),
            )
            elapsed = time.perf_counter() - started
        except Exception as exc:  # noqa: BLE001 — any failure means no model
            self.load_error = f"Failed to load Whisper '{self.model_size}': {exc}"
            logger.error(self.load_error)
            self._model = None
            return False

        self.load_error = None
        logger.info("Whisper '%s' loaded in %.1fs (int8, CPU)", self.model_size, elapsed)
        return True

    def transcribe(self, samples: np.ndarray, language: str) -> tuple[str, Optional[float]]:
        """Transcribe one utterance. Returns (text, confidence)."""
        if self._model is None:
            raise RuntimeError(self.load_error or "Whisper is not loaded")

        # Whisper takes an ISO-639-1 code; the browser sends BCP-47 tags like
        # "en-IN". Splitting is enough — the region is what the ACOUSTIC model
        # uses in the browser, and Whisper is multilingual by language only.
        code = language.split("-")[0].lower() if language else None

        segments, _info = self._model.transcribe(
            samples,
            language=code,
            # beam_size 1 is greedy decoding: measurably faster on CPU, and the
            # accuracy difference on short conversational utterances is small.
            beam_size=1,
            # Whisper hallucinates confident text on silence; this is its own
            # guard against that, and it matters because our VAD will
            # occasionally hand over a near-silent chunk.
            vad_filter=True,
            condition_on_previous_text=False,
        )

        parts: list[str] = []
        probabilities: list[float] = []
        for segment in segments:
            text = segment.text.strip()
            if text:
                parts.append(text)
                # avg_logprob is a log probability; exponentiating gives
                # something on the same 0-1 scale as the sign model's softmax,
                # so the UI can show one kind of confidence.
                probabilities.append(float(np.exp(segment.avg_logprob)))

        if not parts:
            return "", None

        confidence = float(np.mean(probabilities)) if probabilities else None
        return " ".join(parts), confidence


transcriber = WhisperTranscriber()


# --------------------------------------------------------------------------- #
# Audio decoding
# --------------------------------------------------------------------------- #


def _have_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def decode_to_pcm(compressed: bytes) -> np.ndarray:
    """Decode browser audio (WebM/Opus, MP4/AAC, Ogg) to 16 kHz mono float32.

    MediaRecorder emits compressed audio in whatever container the browser
    prefers, and Whisper needs raw samples. ffmpeg handles every format any
    browser produces, which is why it is a prerequisite rather than us pulling
    in a stack of Python decoders that each cover one codec.
    """
    if not compressed:
        return np.zeros(0, dtype=np.float32)

    with tempfile.NamedTemporaryFile(suffix=".webm", delete=True) as source:
        source.write(compressed)
        source.flush()

        result = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                "-i", source.name,
                "-f", "f32le",          # raw 32-bit float
                "-ac", "1",             # mono
                "-ar", str(SAMPLE_RATE),
                "-",
            ],
            capture_output=True,
            check=False,
        )

    if result.returncode != 0 or not result.stdout:
        return np.zeros(0, dtype=np.float32)

    return np.frombuffer(result.stdout, dtype=np.float32)


def rms(samples: np.ndarray) -> float:
    if samples.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))


# --------------------------------------------------------------------------- #
# Utterance assembly
# --------------------------------------------------------------------------- #


class StreamDecoder:
    """Decodes a MediaRecorder stream that arrives in fragments.

    THE BUG THIS EXISTS TO FIX
    --------------------------
    MediaRecorder with a timeslice emits a WebM stream in pieces, and only the
    FIRST piece carries the initialisation segment — the EBML header, the track
    entry, the codec private data. Every later piece is a bare cluster.

    Decoding each piece independently therefore works exactly once. Measured on
    a real Opus/WebM recording split into four:

        chunk 0 alone  -> 5,016 samples   OK
        chunk 1 alone  ->     0 samples   fails
        chunk 2 alone  ->     0 samples   fails
        chunk 3 alone  ->     0 samples   fails

    So the server received the first 250 ms of speech and then silence forever.
    The voice-activity detector saw one burst shorter than MIN_UTTERANCE_S,
    discarded it, and no caption was ever produced. Nothing logged an error,
    because "ffmpeg returned no audio" is indistinguishable from "that chunk
    was quiet".

    THE FIX
    -------
    Keep the whole stream for the current utterance and decode it as one, then
    feed forward only the samples that are new since the last call. ffmpeg gets
    a valid, complete WebM document every time.

    Re-decoding looks wasteful and is affordable: utterances are capped at
    MAX_UTTERANCE_S, decoding 12 s of Opus takes well under 100 ms, and it
    happens in a worker thread. Prepending the header to each fragment instead
    is cheaper but produces gaps and duplicated audio at the seams, which is
    worse than slow.
    """

    def __init__(self) -> None:
        self._header = b""
        self._buffer = b""
        self._consumed = 0

    def push(self, chunk: bytes) -> np.ndarray:
        """Add a fragment; return only the newly decodable samples."""
        if not chunk:
            return np.zeros(0, dtype=np.float32)

        if not self._header:
            # The first fragment is the initialisation segment. Kept so the
            # buffer can be reset to a decodable state after each utterance.
            self._header = chunk
            self._buffer = chunk
        else:
            self._buffer += chunk

        samples = decode_to_pcm(self._buffer)
        if samples.size <= self._consumed:
            # Nothing new decoded. Happens when a fragment lands mid-frame.
            return np.zeros(0, dtype=np.float32)

        fresh = samples[self._consumed :]
        self._consumed = samples.size
        return fresh

    def reset_after_utterance(self) -> None:
        """Start a fresh buffer, keeping the header so it stays decodable.

        Without this the buffer would grow for the whole meeting and every
        decode would get slower.
        """
        self._buffer = self._header
        self._consumed = decode_to_pcm(self._header).size if self._header else 0


class UtteranceBuffer:
    """Accumulates audio and decides where one utterance ends.

    Energy-based rather than a trained VAD: silence is a low root-mean-square
    over a sustained stretch. The failure mode is a sentence split at a long
    pause, which reads fine as captions — far better than a learned VAD's
    failure mode of confidently discarding quiet speech.
    """

    def __init__(self) -> None:
        self._samples: list[np.ndarray] = []
        self._total = 0
        self._silent_run = 0

    def push(self, samples: np.ndarray) -> Optional[np.ndarray]:
        """Add audio; return a completed utterance when one is detected."""
        if samples.size == 0:
            return None

        speaking = rms(samples) >= SILENCE_RMS

        if speaking:
            self._silent_run = 0
            self._samples.append(samples)
            self._total += samples.size
        elif self._samples:
            # Keep trailing silence in the buffer. Cutting it out would clip
            # the final consonant of the last word, and Whisper transcribes a
            # trailing pause more accurately than an abrupt truncation.
            self._samples.append(samples)
            self._total += samples.size
            self._silent_run += samples.size
        else:
            # Silence before anybody spoke is not worth buffering.
            return None

        long_enough_silence = self._silent_run >= SILENCE_DURATION_S * SAMPLE_RATE
        too_long = self._total >= MAX_UTTERANCE_S * SAMPLE_RATE

        if long_enough_silence or too_long:
            return self.flush()

        return None

    def flush(self) -> Optional[np.ndarray]:
        """Return whatever is buffered, if it is worth transcribing."""
        if not self._samples:
            return None

        utterance = np.concatenate(self._samples)
        self._samples = []
        self._total = 0
        self._silent_run = 0

        if utterance.size < MIN_UTTERANCE_S * SAMPLE_RATE:
            return None
        return utterance


# --------------------------------------------------------------------------- #
# Endpoint
# --------------------------------------------------------------------------- #


def _authenticate(token: str) -> Optional[User]:
    """Same contract as the inference socket: a JWT in the query string."""
    payload = decode_access_token(token)
    if payload is None:
        return None

    subject = payload.get("sub")
    try:
        user_id = int(subject)
    except (TypeError, ValueError):
        return None

    with SessionLocal() as session:
        return session.get(User, user_id)


def _error(code: str, message: str) -> dict[str, Any]:
    return {"type": "error", "code": code, "message": message}


@router.websocket("/ws/transcribe/{meeting_code}")
async def transcribe_socket(
    websocket: WebSocket,
    meeting_code: str,
    token: str = Query(..., description="JWT from POST /api/auth/login"),
) -> None:
    """Stream audio in, get transcribed text back."""

    user = _authenticate(token)
    if user is None:
        # Accept first, then close with a code the browser can actually read —
        # rejecting before accepting surfaces as an opaque 1006. Same reasoning
        # as the inference socket.
        await websocket.accept()
        await websocket.send_json(
            _error("UNAUTHORIZED", "Invalid or expired token — please log in again")
        )
        await websocket.close(code=WS_POLICY_VIOLATION, reason="Invalid or expired token")
        return

    await websocket.accept()

    if not transcriber.is_loaded:
        await websocket.send_json(
            _error(
                "MODEL_NOT_LOADED",
                transcriber.load_error
                or "Whisper is not available on this server. Use the Web Speech provider.",
            )
        )
        await websocket.close(code=WS_POLICY_VIOLATION, reason="Whisper unavailable")
        return

    if not _have_ffmpeg():
        await websocket.send_json(
            _error(
                "FFMPEG_MISSING",
                "ffmpeg is not installed on the server, so browser audio cannot be "
                "decoded. Install it with: brew install ffmpeg",
            )
        )
        await websocket.close(code=WS_POLICY_VIOLATION, reason="ffmpeg missing")
        return

    buffer = UtteranceBuffer()
    decoder = StreamDecoder()
    language = "en-IN"

    await websocket.send_json(
        {
            "type": "ready",
            "provider": "whisper",
            "model": transcriber.model_size,
            "sample_rate": SAMPLE_RATE,
            # The client shows a listening indicator instead of partial text,
            # so it needs to know none is coming.
            "provides_interim": False,
        }
    )

    async def transcribe_and_send(utterance: np.ndarray) -> None:
        started = time.perf_counter()
        try:
            # Whisper is CPU-bound and blocking. Running it directly here would
            # stall the event loop for the whole transcription, freezing every
            # other socket this worker serves.
            text, confidence = await asyncio.to_thread(
                transcriber.transcribe, utterance, language
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Transcription failed")
            await websocket.send_json(_error("TRANSCRIBE_FAILED", str(exc)))
            return

        if not text:
            return

        await websocket.send_json(
            {
                "type": "transcript",
                "text": text,
                "confidence": round(confidence, 4) if confidence is not None else None,
                "is_final": True,
                "audio_seconds": round(utterance.size / SAMPLE_RATE, 2),
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            }
        )

    try:
        while True:
            message = await websocket.receive()

            if message.get("type") == "websocket.disconnect":
                break

            # --- control messages ------------------------------------------
            if (text_payload := message.get("text")) is not None:
                try:
                    control = json.loads(text_payload)
                except json.JSONDecodeError:
                    await websocket.send_json(_error("INVALID_MESSAGE", "Malformed JSON"))
                    continue

                if control.get("type") == "config":
                    language = str(control.get("language") or language)
                elif control.get("type") == "flush":
                    # The user turned captions off mid-sentence. Transcribe what
                    # is buffered rather than discarding their last words.
                    remainder = buffer.flush()
                    if remainder is not None:
                        await transcribe_and_send(remainder)
                    await asyncio.to_thread(decoder.reset_after_utterance)
                else:
                    await websocket.send_json(
                        _error("INVALID_MESSAGE", f"Unknown control: {control.get('type')!r}")
                    )
                continue

            # --- audio ------------------------------------------------------
            audio = message.get("bytes")
            if not audio:
                continue

            # Through the stream decoder, NOT decode_to_pcm directly: a bare
            # fragment is not a decodable WebM document. See StreamDecoder.
            samples = await asyncio.to_thread(decoder.push, audio)
            utterance = buffer.push(samples)
            if utterance is not None:
                await transcribe_and_send(utterance)
                # The utterance is done, so the accumulated stream can be
                # dropped back to just the header.
                await asyncio.to_thread(decoder.reset_after_utterance)

    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        logger.exception("Transcribe socket failed for %s", user.name)
        try:
            await websocket.close(code=WS_INTERNAL_ERROR)
        except RuntimeError:
            pass
