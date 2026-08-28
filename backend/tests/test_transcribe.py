"""Tests for the Whisper transcription socket's utterance detection.

WHAT IS TESTED HERE, AND WHAT IS NOT
------------------------------------
Whisper itself is not tested — it is a third-party model, and asserting that it
transcribes audio correctly would be testing OpenAI's work, not ours. These
tests cover the part we wrote: deciding **where one utterance ends**, which is
what turns a stream of 250 ms audio chunks into sentences.

That logic is pure arithmetic over sample arrays, so it runs with no model, no
microphone, no ffmpeg and no network — which also means it keeps working on a
machine where faster-whisper was never installed.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.ws.transcribe import (
    MAX_UTTERANCE_S,
    MIN_UTTERANCE_S,
    SAMPLE_RATE,
    SILENCE_DURATION_S,
    SILENCE_RMS,
    UtteranceBuffer,
    rms,
)


def speech(seconds: float, amplitude: float = 0.2) -> np.ndarray:
    """Audio loud enough to count as somebody talking."""
    count = int(seconds * SAMPLE_RATE)
    # A sine wave rather than random noise: its RMS is predictable, so a failing
    # test points at the buffer rather than at an unlucky random draw.
    t = np.linspace(0, seconds, count, endpoint=False)
    return (amplitude * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def silence(seconds: float) -> np.ndarray:
    return np.zeros(int(seconds * SAMPLE_RATE), dtype=np.float32)


# --------------------------------------------------------------------------- #
# The silence measure itself
# --------------------------------------------------------------------------- #


def test_rms_of_silence_is_zero():
    assert rms(silence(0.5)) == 0.0


def test_rms_of_empty_audio_is_zero_not_nan():
    """An empty chunk arrives at start and stop on some browsers.

    np.mean of an empty array is NaN, and NaN compares false against every
    threshold — so a missing guard here would make silence detection silently
    stop working rather than fail loudly.
    """
    assert rms(np.zeros(0, dtype=np.float32)) == 0.0


def test_speech_registers_above_the_silence_threshold():
    assert rms(speech(0.5)) > SILENCE_RMS


def test_very_quiet_audio_counts_as_silence():
    """Room tone with echo cancellation on sits near 0.005 RMS."""
    assert rms(speech(0.5, amplitude=0.004)) < SILENCE_RMS


# --------------------------------------------------------------------------- #
# Finding the end of an utterance
# --------------------------------------------------------------------------- #


def test_speech_alone_does_not_end_an_utterance():
    """Somebody still talking must not have their sentence cut in half."""
    buffer = UtteranceBuffer()
    for _ in range(6):
        assert buffer.push(speech(0.25)) is None


def test_sustained_silence_ends_the_utterance():
    buffer = UtteranceBuffer()
    buffer.push(speech(1.0))

    # Feed silence in realistic 250 ms chunks until the threshold is crossed.
    result = None
    for _ in range(int(SILENCE_DURATION_S / 0.25) + 2):
        result = buffer.push(silence(0.25))
        if result is not None:
            break

    assert result is not None, "silence never closed the utterance"
    # The speech plus the trailing silence that closed it.
    assert result.size >= SAMPLE_RATE


def test_brief_pause_does_not_end_the_utterance():
    """People pause mid-sentence. Splitting there would chop every sentence.

    250 ms is well under SILENCE_DURATION_S, so this must NOT trigger.
    """
    buffer = UtteranceBuffer()
    buffer.push(speech(0.6))
    assert buffer.push(silence(0.25)) is None
    assert buffer.push(speech(0.6)) is None


def test_silence_before_anyone_speaks_is_discarded():
    """Nothing should be buffered while the room is quiet.

    Without this the buffer would fill with minutes of empty audio and
    eventually hand Whisper a long silent clip, which it reliably hallucinates
    text over.
    """
    buffer = UtteranceBuffer()
    for _ in range(20):
        assert buffer.push(silence(0.25)) is None
    assert buffer.flush() is None


def test_a_very_long_monologue_is_cut_rather_than_buffered_forever():
    """Somebody talking without pause must still produce captions."""
    buffer = UtteranceBuffer()

    result = None
    for _ in range(int(MAX_UTTERANCE_S / 0.5) + 4):
        result = buffer.push(speech(0.5))
        if result is not None:
            break

    assert result is not None, "a continuous talker never got transcribed"
    assert result.size >= MAX_UTTERANCE_S * SAMPLE_RATE * 0.9


def test_a_cough_is_too_short_to_transcribe():
    """Sub-threshold blips are coughs, doors and clipped word onsets.

    Transcribing them wastes a model call and usually produces an invented word.
    """
    buffer = UtteranceBuffer()
    buffer.push(speech(MIN_UTTERANCE_S / 2))
    assert buffer.flush() is None


def test_trailing_silence_is_kept_in_the_utterance():
    """Cutting at the exact moment of silence clips the last consonant.

    Whisper transcribes a trailing pause more accurately than an abrupt
    truncation, so the silence that ENDED the utterance stays part of it.
    """
    buffer = UtteranceBuffer()
    buffer.push(speech(1.0))

    result = None
    for _ in range(8):
        result = buffer.push(silence(0.25))
        if result is not None:
            break

    assert result is not None
    # Strictly longer than the speech alone, i.e. the silence came along.
    assert result.size > SAMPLE_RATE


# --------------------------------------------------------------------------- #
# Flushing
# --------------------------------------------------------------------------- #


def test_flush_returns_buffered_speech():
    """The user turning captions off mid-sentence must not lose their words."""
    buffer = UtteranceBuffer()
    buffer.push(speech(1.0))

    flushed = buffer.flush()
    assert flushed is not None
    assert flushed.size >= SAMPLE_RATE * 0.9


def test_flush_empties_the_buffer():
    buffer = UtteranceBuffer()
    buffer.push(speech(1.0))

    assert buffer.flush() is not None
    assert buffer.flush() is None, "a second flush returned the same audio twice"


def test_buffer_is_reusable_after_an_utterance():
    """One socket carries a whole meeting, so the buffer runs many times."""
    buffer = UtteranceBuffer()

    for _ in range(3):
        buffer.push(speech(1.0))
        assert buffer.flush() is not None


# --------------------------------------------------------------------------- #
# The model wrapper degrades instead of crashing
# --------------------------------------------------------------------------- #


def _whisper_installed() -> bool:
    """Is the PACKAGE importable? Distinct from whether load() has been called.

    An earlier version of these tests guarded on `transcriber.is_loaded`, which
    is False before anything calls load() even when faster-whisper is perfectly
    well installed — so the "not installed" test ran on a machine that had it
    and failed. The condition being tested is availability, not lifecycle.
    """
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False
    return True


@pytest.mark.skipif(_whisper_installed(), reason="faster-whisper IS installed here")
def test_transcriber_reports_a_useful_error_when_unavailable():
    """Whisper is the FALLBACK provider. A backend without it must still start.

    This is the state on a fresh clone: faster-whisper is optional, so `load()`
    has to return False with an actionable message rather than raising.
    """
    from app.ws.transcribe import transcriber

    assert transcriber.load() is False
    assert transcriber.load_error, "a failed load must explain itself"
    # The message has to tell somebody what to actually do about it.
    assert "install" in transcriber.load_error.lower()


def test_predicting_without_a_loaded_model_raises_rather_than_returning_nonsense():
    """A fresh transcriber has no model, whether or not the package exists.

    Returning empty text here would be worse than raising: the socket would
    emit blank captions forever and look like a microphone problem.
    """
    from app.ws.transcribe import WhisperTranscriber

    fresh = WhisperTranscriber()
    with pytest.raises(RuntimeError):
        fresh.transcribe(speech(1.0), "en-IN")


# --------------------------------------------------------------------------- #
# Real transcription — only where the model is actually present
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(not _whisper_installed(), reason="faster-whisper not installed")
def test_whisper_does_not_hallucinate_words_from_silence():
    """The single most important property of this integration.

    Whisper is well known for inventing confident text when given silence, and
    our energy-based VAD will occasionally hand it a near-silent chunk. If that
    produced words, the transcript would fill with sentences nobody said —
    far worse than missing a caption.
    """
    from app.ws.transcribe import transcriber

    if not transcriber.is_loaded and not transcriber.load():
        pytest.skip(f"model unavailable: {transcriber.load_error}")

    text, _confidence = transcriber.transcribe(silence(2.0), "en-IN")
    assert text == "", f"hallucinated {text!r} from silence"


@pytest.mark.skipif(not _whisper_installed(), reason="faster-whisper not installed")
def test_whisper_does_not_hallucinate_words_from_a_pure_tone():
    """A tone is not speech. Neither is a fan, a door, or a chair scraping."""
    from app.ws.transcribe import transcriber

    if not transcriber.is_loaded and not transcriber.load():
        pytest.skip(f"model unavailable: {transcriber.load_error}")

    text, _confidence = transcriber.transcribe(speech(3.0), "en-IN")
    assert text == "", f"hallucinated {text!r} from a sine wave"


# --------------------------------------------------------------------------- #
# The socket itself
# --------------------------------------------------------------------------- #
#
# These use the same in-memory database fixtures as the other WebSocket tests,
# so they never touch MySQL. See conftest.py for why SessionLocal is patched.


def test_transcribe_socket_rejects_a_garbage_token(client):
    """Same auth contract as the inference socket: a JWT in the query string."""
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect("/ws/transcribe/DEMO?token=not-a-real-token") as socket:
            message = socket.receive_json()
            assert message["code"] == "UNAUTHORIZED"
            # Keep reading until the server closes, so the close code surfaces.
            socket.receive_json()

    # 1008 is "policy violation" — the conventional code for an auth failure.
    # Rejecting BEFORE accepting would surface as an opaque 1006 that the
    # browser cannot distinguish from the server being down.
    assert excinfo.value.code == 1008


def test_transcribe_socket_requires_a_token_at_all(client):
    """No token is a 403 from FastAPI's query validation, not a silent accept."""
    with pytest.raises(Exception):
        with client.websocket_connect("/ws/transcribe/DEMO") as socket:
            socket.receive_json()


def test_transcribe_socket_reports_a_missing_model_clearly(client, registered_user):
    """Without Whisper installed, the socket must say so and close.

    This is the expected state on a fresh clone. Streaming audio at a backend
    that cannot transcribe it would burn bandwidth and look like a hang, so the
    socket refuses up front with a code the client acts on.
    """
    from app.ws.transcribe import transcriber

    if transcriber.is_loaded:
        pytest.skip("Whisper is installed here, so this failure path cannot run")

    token = registered_user["access_token"]
    with client.websocket_connect(f"/ws/transcribe/DEMO?token={token}") as socket:
        message = socket.receive_json()

    assert message["type"] == "error"
    assert message["code"] == "MODEL_NOT_LOADED"
    # The message must point at the fix, not just state the problem.
    assert message["message"]
