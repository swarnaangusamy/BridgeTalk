import { SttProvider } from './SttProvider';

import { buildTranscribeSocketUrl } from '../api';

/**
 * Speech recognition by streaming audio to our own backend, which runs Whisper.
 *
 * WHEN THIS IS THE RIGHT PROVIDER
 * -------------------------------
 *   - Firefox and Safari, which have no usable Web Speech API;
 *   - anyone who does not want conversation audio sent to Google;
 *   - accented English, which Whisper handles noticeably better.
 *
 * WHAT IT COSTS
 * -------------
 * **No interim results.** Whisper transcribes a finished chunk of audio, so
 * there is no partial text to stream — `providesInterim` is false and the UI
 * shows a listening indicator instead of half-sentences. This is the single
 * biggest behavioural difference between the two providers and the reason the
 * interface declares it rather than letting a component guess.
 *
 * It is also slower: a caption arrives after the utterance ends plus
 * transcription time, where Web Speech shows words as you say them.
 *
 * HOW AUDIO GETS THERE
 * --------------------
 * MediaRecorder produces compressed chunks; each is sent as a binary WebSocket
 * frame. The backend buffers them, detects the end of an utterance from
 * silence, and transcribes. We deliberately do NOT decode or resample audio in
 * the browser — that work belongs where the model is.
 */

// Short enough that the backend's silence detector reacts promptly, long
// enough that we are not paying WebSocket framing overhead on every syllable.
const CHUNK_MS = 250;

// Ordered by preference. Chrome and Firefox both do Opus in WebM; Safari needs
// MP4. Whisper reads all of them via ffmpeg on the backend.
const CANDIDATE_MIME_TYPES = [
  'audio/webm;codecs=opus',
  'audio/webm',
  'audio/mp4',
  'audio/ogg;codecs=opus',
];

function pickMimeType() {
  if (typeof MediaRecorder === 'undefined') return null;
  return CANDIDATE_MIME_TYPES.find((type) => MediaRecorder.isTypeSupported(type)) ?? null;
}

export class WhisperProvider extends SttProvider {
  constructor({ language = 'en-IN', meetingCode = 'DEMO' } = {}) {
    super();
    this.name = 'Whisper';
    // Chunk-based: finals only. See the class docstring.
    this.providesInterim = false;

    this.language = language;
    this.meetingCode = meetingCode;

    this._stream = null;
    this._recorder = null;
    this._socket = null;
    this._state = 'idle';
    this._closingDeliberately = false;
  }

  static isSupported() {
    return (
      typeof MediaRecorder !== 'undefined' &&
      typeof navigator !== 'undefined' &&
      Boolean(navigator.mediaDevices?.getUserMedia) &&
      pickMimeType() !== null
    );
  }

  setLanguage(language) {
    this.language = language;
    // The backend reads the language per message, so nothing needs restarting.
    if (this._socket?.readyState === WebSocket.OPEN) {
      this._socket.send(JSON.stringify({ type: 'config', language }));
    }
  }

  async start() {
    if (!WhisperProvider.isSupported()) {
      this._setState('unsupported');
      this.onError('unsupported', 'This browser cannot record audio (MediaRecorder missing).');
      return;
    }

    this._closingDeliberately = false;

    try {
      // PROBLEM: echo. The microphone will happily transcribe the other
      // participant coming out of the speakers, producing captions that
      // attribute their words to us. These three constraints are the browser's
      // own answer to that; the UI additionally recommends headphones, because
      // no constraint fully solves it in a loud room.
      this._stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
        video: false,
      });
    } catch (error) {
      this._setState('error');
      const denied = error?.name === 'NotAllowedError' || error?.name === 'SecurityError';
      this.onError(
        denied ? 'not-allowed' : 'microphone',
        denied
          ? 'Microphone permission denied. Allow it in your browser, then turn captions on again.'
          : `Could not open the microphone: ${error?.message ?? error}`,
      );
      return;
    }

    await this._openSocket();
    if (!this._socket) return;

    const mimeType = pickMimeType();
    this._recorder = new MediaRecorder(this._stream, { mimeType });

    this._recorder.ondataavailable = (event) => {
      // Empty chunks happen on some browsers at start/stop; sending them would
      // make the backend's silence detector see phantom audio.
      if (!event.data || event.data.size === 0) return;
      if (this._socket?.readyState !== WebSocket.OPEN) return;

      // Binary frame: the audio itself, with no JSON wrapper or base64
      // expansion. Base64 would cost a third more bandwidth for nothing.
      this._socket.send(event.data);
    };

    this._recorder.start(CHUNK_MS);
    this._setState('listening');
  }

  _openSocket() {
    return new Promise((resolve) => {
      const socket = new WebSocket(buildTranscribeSocketUrl(this.meetingCode));
      socket.binaryType = 'arraybuffer';

      socket.onopen = () => {
        socket.send(JSON.stringify({ type: 'config', language: this.language }));
        this._socket = socket;
        resolve();
      };

      socket.onmessage = (event) => {
        let message;
        try {
          message = JSON.parse(event.data);
        } catch {
          return;
        }

        if (message.type === 'transcript' && message.text) {
          this.onFinal(message.text, message.confidence ?? null, Date.now());
        } else if (message.type === 'error') {
          this.onError(message.code ?? 'server', message.message ?? 'Transcription failed');
          // A missing model is not recoverable by retrying, so stop rather
          // than streaming audio at a backend that cannot use it.
          if (message.code === 'MODEL_NOT_LOADED') {
            this._setState('error');
            this.stop();
          }
        }
      };

      socket.onerror = () => {
        // The browser withholds the reason; onclose carries the useful code.
      };

      socket.onclose = () => {
        this._socket = null;
        if (this._closingDeliberately) return;
        this._setState('error');
        this.onError(
          'disconnected',
          'Lost the connection to the transcription service. Is the backend running?',
        );
      };

      // If the socket never opens, resolve anyway so start() can report a
      // clean error instead of hanging forever on an unresolved promise.
      setTimeout(() => {
        if (!this._socket) {
          this._setState('error');
          this.onError('disconnected', 'Could not reach the transcription service.');
          resolve();
        }
      }, 5_000);
    });
  }

  async stop() {
    this._closingDeliberately = true;

    if (this._recorder && this._recorder.state !== 'inactive') {
      try {
        this._recorder.stop();
      } catch {
        // Already stopped.
      }
    }
    this._recorder = null;

    // Ask the backend to flush whatever it is holding, so the last sentence is
    // not silently discarded when the user turns captions off mid-utterance.
    if (this._socket?.readyState === WebSocket.OPEN) {
      this._socket.send(JSON.stringify({ type: 'flush' }));
      this._socket.close();
    }
    this._socket = null;

    // Releasing the tracks turns the microphone indicator off. Skipping this
    // leaves the browser showing "recording" after the user stopped, which is
    // an alarming thing for an accessibility tool to do.
    this._stream?.getTracks().forEach((track) => track.stop());
    this._stream = null;

    this._setState('idle');
  }

  async pause() {
    // Unlike Web Speech, we own the MediaRecorder, so a real pause is possible:
    // the microphone stays open and resuming costs nothing.
    if (this._recorder?.state === 'recording') {
      this._recorder.pause();
      this._setState('idle');
    }
  }

  async resume() {
    if (this._recorder?.state === 'paused') {
      this._recorder.resume();
      this._setState('listening');
    } else {
      await this.start();
    }
  }
}
