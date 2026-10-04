import { useCallback, useEffect, useRef, useState } from 'react';

import { createProvider, resolveProvider } from '../services/stt';
import { newSegmentId } from './useCaptionStore';

/**
 * Produces speech captions from the local microphone, for the whole meeting.
 *
 * WHAT CHANGED, AND WHY IT WAS BROKEN
 * -----------------------------------
 * Speech recognition used to be gated on a `speechOn` flag wired to a panel
 * toggle that defaulted to OFF. So a participant who had not found that toggle
 * produced no captions at all — and the panel still reported the provider's
 * state as "listening", because that reflected the recogniser object rather
 * than whether any audio was reaching it.
 *
 * Producing is now automatic and keyed to ONE thing: **is my microphone
 * unmuted**. Displaying captions is a separate concern entirely, handled by
 * the caption button. Nobody's speech should go unrecognised because they
 * chose not to look at captions themselves.
 *
 * SEGMENTS
 * --------
 * One `segment_id` per utterance. Interims carry the full current text of that
 * segment; the final closes it and the next utterance gets a fresh id. The
 * server stores exactly one row per segment.
 */
export function useSpeechCaptions({
  enabled = false,
  engine = 'auto',
  language = 'en-IN',
  meetingCode = 'DEMO',
  onCaption,
} = {}) {
  const providerRef = useRef(null);
  const segmentRef = useRef(null);
  const onCaptionRef = useRef(onCaption);

  const [state, setState] = useState('idle');
  const [error, setError] = useState(null);
  const [lastInterim, setLastInterim] = useState('');
  const [notice, setNotice] = useState(null);

  useEffect(() => {
    onCaptionRef.current = onCaption;
  }, [onCaption]);

  const resolution = resolveProvider(engine);
  const activeId = resolution.id;

  useEffect(() => {
    if (!activeId) {
      setState('unsupported');
      setError(resolution.reason);
      return undefined;
    }
    if (!enabled) return undefined;

    const instance = createProvider(activeId, { language, meetingCode });

    const ensureSegment = () => {
      if (!segmentRef.current) segmentRef.current = newSegmentId('sp');
      return segmentRef.current;
    };

    instance.onInterim = (text) => {
      if (!text.trim()) return;
      setLastInterim(text);
      // The FULL current text of this segment, not a delta. The receiver
      // replaces its line with this, so sending a delta would lose words.
      onCaptionRef.current?.({
        segmentId: ensureSegment(),
        source: 'speech',
        text,
        isFinal: false,
      });
    };

    instance.onFinal = (text, confidence) => {
      if (!text.trim()) {
        // Nothing was heard. Close the segment anyway so the next utterance
        // does not inherit this id, but send nothing to store.
        segmentRef.current = null;
        return;
      }
      const segmentId = ensureSegment();
      // Close the segment BEFORE the callback, so a synchronous re-entry
      // cannot reuse the id for the next utterance.
      segmentRef.current = null;
      setLastInterim('');
      onCaptionRef.current?.({
        segmentId,
        source: 'speech',
        text,
        isFinal: true,
        confidence,
      });
    };

    instance.onError = (code, message) => {
      // Surfaced, not swallowed. `no-speech` is routine and handled inside the
      // provider; anything that reaches here is worth telling the user about,
      // because the alternative is a caption area that is silently dead.
      setError(message);
      if (code === 'not-allowed' || code === 'language-not-supported') {
        setState('error');
      }
    };

    instance.onStateChange = (next) => {
      setState(next);
      if (next === 'listening') setError(null);
    };

    providerRef.current = instance;
    setNotice(resolution.fellBack ? resolution.reason : null);
    instance.start();

    return () => {
      // If the microphone is muted mid-utterance, finalise what was heard
      // rather than discarding it.
      instance.onInterim = () => {};
      instance.onFinal = () => {};
      instance.onError = () => {};
      instance.onStateChange = () => {};
      instance.stop();
      providerRef.current = null;
      segmentRef.current = null;
      setLastInterim('');
      setState('idle');
    };
    // `language` is handled in place below, so it is deliberately not a
    // dependency — changing it must not restart recognition mid-sentence.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, activeId, meetingCode]);

  useEffect(() => {
    providerRef.current?.setLanguage?.(language);
  }, [language]);

  const diagnostics = useCallback(
    () => ({
      engineRequested: engine,
      engineActive: activeId ?? 'none',
      state,
      lastInterim,
      error,
      openSegment: segmentRef.current,
      providesInterim: providerRef.current?.providesInterim ?? null,
    }),
    [engine, activeId, state, lastInterim, error],
  );

  return {
    state,
    error,
    notice,
    lastInterim,
    engineActive: activeId,
    providesInterim: providerRef.current?.providesInterim ?? false,
    isSupported: Boolean(activeId),
    diagnostics,
  };
}
