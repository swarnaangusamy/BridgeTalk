import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Interview Mode: logs when this tab loses or regains focus.
 *
 * BE HONEST ABOUT WHAT THIS IS
 * ----------------------------
 * This is a **deterrent, not proctoring**, and the difference is not a
 * technicality. The browser will tell us two things and nothing more:
 *
 *   - `visibilitychange` — the tab became hidden (switched away, minimised)
 *   - `blur`             — the window lost keyboard focus (clicked another app)
 *
 * It cannot see a second monitor, a phone under the desk, notes on paper, or
 * another person in the room. It cannot tell "opened the answer key" from
 * "a notification stole focus for half a second". Anyone who wants to cheat
 * around it can, trivially.
 *
 * What it is genuinely good for: making an honest participant aware that
 * attention is being recorded, which is most of what a deterrent does. The
 * README says exactly this, and so should you if it comes up in a review.
 *
 * TWO EVENTS, ONE ACTION
 * ----------------------
 * Switching apps usually fires both `blur` and `visibilitychange`. Logging
 * both would double-count every incident, so the hook tracks whether it
 * already considers itself "away" and only logs a transition.
 */
export function useFocusMonitor({ enabled = false, onEvent } = {}) {
  const [awayCount, setAwayCount] = useState(0);
  const [isAway, setIsAway] = useState(false);
  const [lastEvent, setLastEvent] = useState(null);

  const awayRef = useRef(false);
  const onEventRef = useRef(onEvent);

  useEffect(() => {
    onEventRef.current = onEvent;
  }, [onEvent]);

  const report = useCallback((eventType) => {
    setLastEvent({ type: eventType, at: new Date().toISOString() });
    onEventRef.current?.(eventType);
  }, []);

  useEffect(() => {
    if (!enabled) return undefined;

    const goAway = (eventType) => {
      // Deduplicate: blur and visibilitychange both fire for one app switch.
      if (awayRef.current) return;
      awayRef.current = true;
      setIsAway(true);
      setAwayCount((count) => count + 1);
      report(eventType);
    };

    const comeBack = () => {
      if (!awayRef.current) return;
      awayRef.current = false;
      setIsAway(false);
      report('return');
    };

    const handleVisibility = () => {
      if (document.hidden) goAway('hidden');
      else comeBack();
    };

    const handleBlur = () => goAway('blur');
    const handleFocus = () => comeBack();

    document.addEventListener('visibilitychange', handleVisibility);
    window.addEventListener('blur', handleBlur);
    window.addEventListener('focus', handleFocus);

    return () => {
      document.removeEventListener('visibilitychange', handleVisibility);
      window.removeEventListener('blur', handleBlur);
      window.removeEventListener('focus', handleFocus);
    };
  }, [enabled, report]);

  // Reset when the mode is switched off, so re-enabling starts from zero
  // rather than resuming a stale count from earlier in the meeting.
  useEffect(() => {
    if (!enabled) {
      awayRef.current = false;
      setIsAway(false);
      setAwayCount(0);
      setLastEvent(null);
    }
  }, [enabled]);

  return { awayCount, isAway, lastEvent };
}
