/**
 * Interview Mode panel: the host's toggle and violation log, or the
 * participant's status.
 *
 * The honesty notice is part of the component, not a footnote elsewhere. A
 * participant being monitored should be able to read exactly what is and is
 * not recorded in the same place as the counter that is recording it.
 *
 * The host sees a different panel from the participant, because they need
 * different things: the host needs to know WHO has left and how often, and
 * whether anyone's browser is enforcing less than the others. The participant
 * needs to know they are being recorded and how many times so far.
 */
function formatAway(ms) {
  if (!ms) return '—';
  const seconds = Math.round(ms / 1000);
  if (seconds < 60) return `${seconds}s`;
  return `${Math.floor(seconds / 60)}m ${String(seconds % 60).padStart(2, '0')}s`;
}

export default function ModeSwitch({
  enabled,
  isHost = false,
  awayCount = 0,
  isAway = false,
  capabilities = { fullscreen: true, keyboardLock: true },
  keyboardLocked = false,
  violationLog = [],
  maxViolations = 3,
  onToggle,
}) {
  // The host always sees the control, so they can switch the mode ON. Everyone
  // else sees this panel only while it is running.
  if (!enabled && !isHost) return null;

  const overLimit = violationLog.filter((row) => row.away_count >= maxViolations);

  return (
    <section
      className={`rounded-xl border p-4 ${
        enabled
          ? awayCount > 0 || overLimit.length
            ? 'border-signal-bad/50 bg-signal-bad/10'
            : 'border-signal-warn/50 bg-signal-warn/10'
          : 'border-ink-700 bg-ink-800'
      }`}
      aria-labelledby="interview-mode-heading"
    >
      <header className="flex items-center justify-between gap-3">
        <h2 id="interview-mode-heading" className="font-semibold">
          Interview mode
        </h2>

        {isHost ? (
          <button
            type="button"
            onClick={onToggle}
            aria-pressed={enabled}
            className={`rounded-md border px-3 py-1 text-sm font-medium ${
              enabled
                ? 'border-signal-warn/60 bg-signal-warn/20 text-signal-warn'
                : 'border-ink-700 bg-ink-900 text-slate-300 hover:bg-ink-700'
            }`}
          >
            {enabled ? 'On' : 'Off'}
          </button>
        ) : (
          <span
            className={`rounded px-2 py-0.5 text-xs font-semibold uppercase ${
              isAway ? 'bg-signal-bad/20 text-signal-bad' : 'bg-signal-ok/20 text-signal-ok'
            }`}
            role="status"
            aria-live="polite"
          >
            {isAway ? 'Away — recorded' : 'In the meeting'}
          </span>
        )}
      </header>

      {!enabled && isHost && (
        <p className="mt-2 text-xs text-slate-400">
          Switching this on tells every other participant, puts their meeting
          into fullscreen, and records when they leave the tab.
        </p>
      )}

      {enabled && (
        <>
          {/* --- host: who has left ---------------------------------------- */}
          {isHost ? (
            <div className="mt-3">
              {violationLog.length === 0 ? (
                <p className="text-sm text-slate-300" role="status" aria-live="polite">
                  No one has left the meeting tab.
                </p>
              ) : (
                <>
                  <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
                    Participants who left
                  </h3>
                  <ul className="space-y-1.5" aria-live="polite">
                    {violationLog.map((row) => (
                      <li
                        key={row.user_id}
                        className="flex items-baseline justify-between gap-2 text-sm"
                      >
                        <span className="text-slate-200">{row.user_name}</span>
                        <span className="tabular-nums text-slate-400">
                          {row.away_count}×
                          {row.longest_away_ms > 0 && (
                            <> · longest {formatAway(row.longest_away_ms)}</>
                          )}
                        </span>
                      </li>
                    ))}
                  </ul>
                </>
              )}

              {/* The prompt, not an automatic removal. Ejecting someone from
                  an interview is a judgement call, and the host may well know
                  the absence was legitimate. */}
              {overLimit.length > 0 && (
                <p
                  className="mt-3 rounded-lg border border-signal-bad/50 bg-signal-bad/15 p-2 text-xs text-slate-100"
                  role="alert"
                >
                  <strong>
                    {overLimit.map((row) => row.user_name).join(', ')}
                  </strong>{' '}
                  {overLimit.length === 1 ? 'has' : 'have'} left{' '}
                  {maxViolations} or more times. You can end the meeting from the
                  control bar if you want to stop here.
                </p>
              )}
            </div>
          ) : (
            <p className="mt-2 text-sm text-slate-200">
              Times you left this window:{' '}
              <strong className="tabular-nums text-lg">{awayCount}</strong>
              {awayCount > 0 && awayCount < maxViolations && (
                <span className="text-slate-400">
                  {' '}· {maxViolations - awayCount} more before the host is
                  prompted
                </span>
              )}
            </p>
          )}

          {/* --- what is actually enforced in THIS browser ---------------- */}
          <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
            <dt className="text-slate-400">Fullscreen</dt>
            <dd className={capabilities.fullscreen ? 'text-signal-ok' : 'text-signal-warn'}>
              {capabilities.fullscreen ? 'available' : 'not supported'}
            </dd>
            <dt className="text-slate-400">Keyboard lock</dt>
            <dd className={capabilities.keyboardLock ? 'text-signal-ok' : 'text-signal-warn'}>
              {capabilities.keyboardLock
                ? keyboardLocked
                  ? 'active'
                  : 'available'
                : 'not supported'}
            </dd>
          </dl>

          {(!capabilities.fullscreen || !capabilities.keyboardLock) && (
            <p className="mt-2 text-xs text-signal-warn">
              Reduced enforcement in this browser. Leaving is still detected and
              recorded. Keyboard lock needs Chrome or Edge.
            </p>
          )}

          <p className="mt-2 text-xs text-slate-400">
            This records only when this browser tab loses focus or is hidden. It
            cannot see other devices, other people in the room, or anything
            outside this tab. It is a deterrent, not proctoring.
          </p>
        </>
      )}
    </section>
  );
}
