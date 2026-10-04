/**
 * The blocking dialog shown to a non-host the moment Interview Mode starts.
 *
 * WHY IT BLOCKS, AND WHY THE BUTTON MATTERS TECHNICALLY
 * -----------------------------------------------------
 * Two reasons, and the second is not obvious:
 *
 *   1. Consent. Being monitored without being told is indefensible, and this
 *      is the only screen where the participant learns what is recorded.
 *   2. Fullscreen requires a user gesture. The browser will refuse
 *      `requestFullscreen()` called from a timer or an effect. The
 *      "I understand" click IS that gesture — which is why enforcement starts
 *      here rather than automatically when the mode is switched on.
 *
 * WHAT IT PROMISES
 * ----------------
 * Exactly what the browser can deliver, and no more. It does not claim tab
 * switching is prevented, because no web page can prevent it. It says leaving
 * is detected, reported and recorded, which is true.
 */
export default function InterviewModeDialog({ hostName, capabilities, onAcknowledge }) {
  const reduced = !capabilities.fullscreen || !capabilities.keyboardLock;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink-900/95 p-6"
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="interview-dialog-title"
      aria-describedby="interview-dialog-body"
    >
      <div className="max-w-lg rounded-2xl border border-signal-warn/50 bg-ink-800 p-6 shadow-2xl">
        <h2
          id="interview-dialog-title"
          className="text-2xl font-bold text-slate-50"
        >
          Interview mode is on
        </h2>
        <p className="mt-1 text-sm text-slate-400">
          {hostName ? `Switched on by ${hostName}.` : 'Switched on by the host.'}
        </p>

        <div id="interview-dialog-body" className="mt-4 space-y-3 text-sm text-slate-200">
          <p>While interview mode is on:</p>
          <ul className="list-disc space-y-1.5 pl-5">
            <li>This meeting will go <strong>fullscreen</strong>.</li>
            <li>
              Switching to another tab, window or application is{' '}
              <strong>not allowed</strong>.
            </li>
            <li>
              If you leave, it is <strong>detected</strong>, the host is{' '}
              <strong>told straight away</strong>, and it is{' '}
              <strong>recorded</strong> with how long you were away.
            </li>
            <li>The meeting view is covered until you come back.</li>
          </ul>

          {/* Say plainly what this cannot do. Overstating it is the fastest
              way to lose a participant's trust — and an examiner's. */}
          <p className="rounded-lg border border-ink-700 bg-ink-900 p-3 text-xs text-slate-400">
            <strong className="text-slate-300">What this cannot do:</strong> a web
            page cannot truly stop you leaving, and this does not watch your
            room, your phone, or a second screen. It records when this tab loses
            focus. It is a deterrent, not surveillance.
          </p>

          {reduced && (
            <p
              className="rounded-lg border border-signal-warn/40 bg-signal-warn/10 p-3 text-xs text-slate-200"
              role="status"
            >
              <strong>Reduced enforcement in this browser.</strong>{' '}
              {!capabilities.fullscreen && 'Fullscreen is unavailable. '}
              {!capabilities.keyboardLock &&
                'Keyboard shortcuts cannot be captured (this needs Chrome or Edge). '}
              Leaving will still be detected and reported. The host is told that
              your browser has reduced enforcement.
            </p>
          )}

          <p className="text-xs text-slate-400">
            Sign and speech captions work exactly as normal.
          </p>
        </div>

        <button
          type="button"
          onClick={onAcknowledge}
          autoFocus
          className="btn-primary mt-5 w-full"
        >
          I understand
        </button>
      </div>
    </div>
  );
}
