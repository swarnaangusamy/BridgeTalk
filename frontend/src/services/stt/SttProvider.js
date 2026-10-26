/**
 * The contract every speech-to-text provider implements.
 *
 * WHY AN ABSTRACTION AT ALL
 * -------------------------
 * The two providers are not merely different implementations of one idea —
 * they behave differently in ways a caption UI has to know about:
 *
 *   Web Speech   streams interim text word by word, is Chromium-only, and
 *                sends audio to Google's servers for recognition.
 *   Whisper      runs on our own backend, works in any browser, and is
 *                chunk-based, so it produces FINALS ONLY — there is no such
 *                thing as a partial result to show.
 *
 * Hiding that behind one interface is what lets `useSpeechCaptions` and the
 * caption bar stay identical regardless of which is running. The one
 * difference a component genuinely must handle is declared explicitly as
 * `providesInterim`, rather than being discovered when partial text never
 * arrives and the UI looks frozen.
 *
 * Lifecycle:
 *
 *      new Provider(options)
 *        .start()     -> 'listening'
 *        .pause()     -> 'idle', microphone kept
 *        .resume()    -> 'listening'
 *        .stop()      -> 'idle', microphone RELEASED
 *
 * Callbacks are assigned as properties rather than passed to the constructor,
 * so React can swap a handler between renders without rebuilding the provider
 * and interrupting recognition mid-sentence.
 */

/** @typedef {'idle'|'listening'|'error'|'unsupported'} SttState */

export class SttProvider {
  constructor() {
    /** Human-readable, shown in the status line. */
    this.name = 'unknown';
    /** False for chunk-based providers such as Whisper. */
    this.providesInterim = false;

    /** @type {(text: string) => void} */
    this.onInterim = () => {};
    /** @type {(text: string, confidence: number|null, timestamp: number) => void} */
    this.onFinal = () => {};
    /** @type {(code: string, message: string) => void} */
    this.onError = () => {};
    /** @type {(state: SttState) => void} */
    this.onStateChange = () => {};
  }

  /** True if this provider can run in the current browser. */
  static isSupported() {
    return false;
  }

  async start() {
    throw new Error('start() not implemented');
  }

  /** Stop recognising and release the microphone. */
  async stop() {
    throw new Error('stop() not implemented');
  }

  /** Stop recognising but keep the microphone open, for a fast resume. */
  async pause() {
    return this.stop();
  }

  async resume() {
    return this.start();
  }

  /**
   * Internal helper so subclasses report state through one path. Emitting the
   * same state twice would make a React consumer re-render for nothing.
   */
  _setState(state) {
    if (state === this._state) return;
    this._state = state;
    this.onStateChange(state);
  }
}
