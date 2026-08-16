/**
 * Interview Mode indicator and warning counter.
 *
 * The honesty notice is part of the component, not a footnote somewhere else.
 * A participant being monitored should be able to see exactly what is and is
 * not being recorded, in the same place as the counter that is recording it.
 */
export default function ModeSwitch({ enabled, awayCount, isAway }) {
  if (!enabled) return null;

  return (
    <section
      className={`rounded-xl border p-4 ${
        awayCount > 0
          ? 'border-signal-warn/50 bg-signal-warn/10'
          : 'border-ink-700 bg-ink-800'
      }`}
      aria-labelledby="interview-mode-heading"
    >
      <header className="flex items-center justify-between gap-3">
        <h2 id="interview-mode-heading" className="font-semibold">
          Interview Mode
        </h2>
        <span
          className={`rounded px-2 py-0.5 text-xs font-semibold uppercase ${
            isAway ? 'bg-signal-bad/20 text-signal-bad' : 'bg-signal-ok/20 text-signal-ok'
          }`}
          role="status"
          aria-live="polite"
        >
          {isAway ? 'Window not focused' : 'Focused'}
        </span>
      </header>

      <p className="mt-2 text-sm text-slate-200">
        Times you left this window:{' '}
        <strong className="tabular-nums text-lg">{awayCount}</strong>
      </p>

      <p className="mt-2 text-xs text-slate-400">
        This records only when this browser tab loses focus or is hidden. It
        cannot see other devices, other people in the room, or anything outside
        this tab. It is a deterrent, not proctoring.
      </p>
    </section>
  );
}
