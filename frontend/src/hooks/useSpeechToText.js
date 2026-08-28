import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { createProvider, PROVIDERS, resolveProvider } from '../services/stt';

/**
 * Speech recognition, independent of which engine is doing it.
 *
 * This is the *other* direction of BridgeTalk: the hearing participant speaks
 * and their words appear as captions for the deaf participant. Video calls
 * have done this for years; the novel half of this project is the sign
 * direction.
 *
 * WHAT THIS HOOK IS AND IS NOT
 * ----------------------------
 * It is lifecycle and state. The recognition logic itself lives in the
 * providers under services/stt — Web Speech in one, Whisper in the other —
 * because those two behave differently enough that interleaving them here
 * would produce a thicket of conditionals.
 *
 * The provider is rebuilt when the engine or the meeting changes, and NOT when
 * the language changes: a running provider handles that itself, so switching
 * language mid-sentence does not drop the sentence.
 *
 * PUBLIC API
 * ----------
 * `isSupported`, `listening`, `interimText`, `error`, `start`, `stop` are
 * unchanged from the Web-Speech-only version of this hook, so existing callers
 * keep working untouched. Everything else is additive.
 */

export function useSpeechToText({
  enabled = false,
  language = 'en-IN',
  provider: preferredProvider = 'webspeech',
  meetingCode = 'DEMO',
  onResult,
} = {}) {
  const providerRef = useRef(null);
  const wantListeningRef = useRef(false);

  const [state, setState] = useState('idle'); // idle | listening | error | unsupported
  const [interimText, setInterimText] = useState('');
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);

  // Which provider we can actually run, which may not be the one asked for.
  const resolution = useMemo(() => resolveProvider(preferredProvider), [preferredProvider]);
  const activeId = resolution.id;

  // Held in a ref so a new callback identity does not tear down recognition
  // mid-sentence on every parent render.
  const onResultRef = useRef(onResult);
  useEffect(() => {
    onResultRef.current = onResult;
  }, [onResult]);

  // --- build the provider ---------------------------------------------------
  // Deliberately NOT keyed on `language`: the provider updates that in place.
  useEffect(() => {
    if (!activeId) {
      setState('unsupported');
      setError(resolution.reason);
      return undefined;
    }

    const instance = createProvider(activeId, { language, meetingCode });

    instance.onInterim = (text) => {
      setInterimText(text);
      // Interim results update the live caption but are never persisted — the
      // recogniser revises them word by word as it hears more.
      onResultRef.current?.({ text, isFinal: false, confidence: null });
    };

    instance.onFinal = (text, confidence, timestamp) => {
      setInterimText('');
      onResultRef.current?.({ text, isFinal: true, confidence, timestamp });
    };

    instance.onError = (code, message) => {
      setError(message);
      // A denied microphone or an unsupported language will not fix itself, so
      // stop asking. Anything else may recover on the next utterance.
      if (code === 'not-allowed' || code === 'language-not-supported') {
        wantListeningRef.current = false;
      }
    };

    instance.onStateChange = (next) => {
      setState(next);
      if (next === 'listening') setError(null);
    };

    providerRef.current = instance;
    setNotice(resolution.fellBack ? resolution.reason : null);

    return () => {
      // Releasing the microphone on unmount is not optional: leaving it open
      // shows the browser's recording indicator after the user has navigated
      // away, which is an alarming thing for an accessibility tool to do.
      wantListeningRef.current = false;
      instance.onInterim = () => {};
      instance.onFinal = () => {};
      instance.onError = () => {};
      instance.onStateChange = () => {};
      instance.stop();
      providerRef.current = null;
      setInterimText('');
      setState('idle');
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeId, meetingCode]);

  // --- language changes, without rebuilding ---------------------------------
  useEffect(() => {
    providerRef.current?.setLanguage?.(language);
  }, [language]);

  const start = useCallback(() => {
    wantListeningRef.current = true;
    setError(null);
    providerRef.current?.start();
  }, []);

  const stop = useCallback(() => {
    wantListeningRef.current = false;
    providerRef.current?.stop();
    setInterimText('');
  }, []);

  // --- follow the `enabled` flag -------------------------------------------
  useEffect(() => {
    if (!providerRef.current) return;
    if (enabled) start();
    else stop();
  }, [enabled, start, stop, activeId]);

  const entry = activeId ? PROVIDERS[activeId] : null;

  return {
    // --- unchanged API, so existing callers keep working ---
    isSupported: Boolean(activeId),
    listening: state === 'listening',
    interimText,
    error,
    start,
    stop,

    // --- additive ---
    state,
    providerId: activeId,
    providerName: entry?.label ?? 'none',
    providerNote: entry?.note ?? null,
    // False for Whisper. The UI shows a listening indicator rather than
    // partial text when this is false, instead of appearing frozen.
    providesInterim: providerRef.current?.providesInterim ?? false,
    language,
    notice,
    pause: () => providerRef.current?.pause(),
    resume: () => providerRef.current?.resume(),
  };
}
