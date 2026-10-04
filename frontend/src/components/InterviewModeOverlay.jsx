/**
 * Covers the meeting when a participant has left, until they come back.
 *
 * WHY COVER THE MEETING AT ALL
 * ----------------------------
 * Detection and logging alone are passive — the participant gets what they
 * went looking for and the host reads about it afterwards. Covering the view
 * makes leaving cost something immediately: they cannot see or follow the
 * meeting while they are away, so the escape is not free.
 *
 * It is deliberately NOT dismissible by clicking away. The only route out is
 * re-entering fullscreen, which needs a user gesture — hence the button.
 */
export default function InterviewModeOverlay({
  awayCount,
  maxViolations,
  isFullscreen,
  onReturn,
}) {
  const remaining = Math.max(0, maxViolations - awayCount);

  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-signal-bad/15 backdrop-blur-md p-6"
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="interview-overlay-title"
    >
      <div className="max-w-md rounded-2xl border border-signal-bad/60 bg-ink-800 p-6 text-center shadow-2xl">
        <h2
          id="interview-overlay-title"
          className="text-2xl font-bold text-signal-bad"
        >
          You left the meeting tab
        </h2>

        <p className="mt-3 text-sm text-slate-200">
          Interview mode is on. This has been recorded and the host has been
          notified.
        </p>

        <p className="mt-2 text-sm text-slate-300">
          Times recorded: <strong className="tabular-nums text-lg">{awayCount}</strong>
          {remaining > 0 ? (
            <>
              {' '}
              · <span className="text-slate-400">
                {remaining} more before the host is prompted to remove you
              </span>
            </>
          ) : (
            <>
              {' '}
              · <span className="text-signal-bad">
                the host has been prompted to remove you
              </span>
            </>
          )}
        </p>

        {!isFullscreen && (
          <p className="mt-3 text-xs text-slate-400">
            The meeting must be fullscreen to continue. Re-entering fullscreen
            needs a click, so the browser will not do it on its own.
          </p>
        )}

        <button type="button" onClick={onReturn} autoFocus className="btn-primary mt-5 w-full">
          Return to the meeting
        </button>
      </div>
    </div>
  );
}
