import { useEffect, useState } from 'react';

/**
 * The current time, re-rendered once a minute.
 *
 * WHY IT ALIGNS TO THE MINUTE BOUNDARY
 * ------------------------------------
 * A plain 60-second interval drifts: if the component mounts at 10:00:59 the
 * clock shows 10:00 for one second, then 10:01 for fifty-nine, then 10:02 at
 * 10:01:59 — always most of a minute late. Scheduling the first tick for the
 * next real minute boundary and only then settling into a 60 s interval keeps
 * the displayed minute correct.
 *
 * Once a minute, not once a second, because neither the top bar nor the
 * control bar shows seconds, and a 1 Hz re-render of the meeting page would
 * re-render the stage and the caption area for nothing.
 */
export function useClock() {
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    let interval;
    const msToNextMinute = 60_000 - (Date.now() % 60_000);

    const timeout = setTimeout(() => {
      setNow(new Date());
      interval = setInterval(() => setNow(new Date()), 60_000);
    }, msToNextMinute);

    return () => {
      clearTimeout(timeout);
      clearInterval(interval);
    };
  }, []);

  return now;
}
