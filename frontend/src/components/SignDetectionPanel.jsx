/**
 * Live prediction readout: current letter, confidence, sentence, connection
 * state and latency.
 *
 * Accessibility is the point of this project, so the panel is built to be
 * usable without seeing it:
 *   - the accumulated sentence is an aria-live region, so a screen reader
 *     announces new text as it arrives;
 *   - the confidence bar carries proper progressbar semantics rather than
 *     being a bare coloured <div>;
 *   - status is conveyed by text as well as colour, so it survives both
 *     colour blindness and a monochrome projector.
 */

import RecognitionModeToggle from './RecognitionModeToggle';

const STATUS_LABELS = {
  idle: 'Not connected',
  connecting: 'Connecting…',
  open: 'Connected',
  reconnecting: 'Reconnecting…',
  closed: 'Disconnected',
  error: 'Connection error',
};

const STATUS_STYLES = {
  idle: 'text-slate-400',
  connecting: 'text-signal-warn',
  open: 'text-signal-ok',
  reconnecting: 'text-signal-warn',
  closed: 'text-signal-bad',
  error: 'text-signal-bad',
};

function confidenceColour(value, stable) {
  if (stable) return 'bg-signal-ok';
  if (value >= 0.5) return 'bg-bridge-500';
  return 'bg-signal-warn';
}

export default function SignDetectionPanel({
  status,
  prediction,
  sentence,
  serverError,
  modelInfo,
  dynamicModelInfo,
  islModelInfo,
  handDetected,
  mode = 'static',
  onModeChange,
  onClear,
  onBackspace,
}) {
  const label = prediction?.label ?? '—';
  const confidence = prediction?.confidence ?? 0;
  const stable = prediction?.stable ?? false;
  const latency = prediction?.latency_ms;

  // Word mode cannot predict anything until a full window of frames has been
  // collected — three seconds at 10 FPS. Without showing that, the UI looks
  // broken for the first three seconds every time the mode is selected.
  const buffering = prediction?.buffering === true;
  const bufferFilled = prediction?.buffer_filled ?? 0;
  const bufferLength = prediction?.buffer_length ?? 0;

  const showingLetter = handDetected && label !== 'nothing' && label !== '—';
  const unitNoun = mode === 'dynamic' ? 'word' : 'letter';
  // ISL letters need both hands; saying so is the single most useful
  // correction to give a signer whose letters are not registering.
  const needsBothHands = mode === 'isl' && prediction?.hands_seen === 1;

  return (
    <section className="panel flex flex-col gap-5" aria-labelledby="sign-detection-heading">
      <header className="flex items-baseline justify-between gap-4">
        <h2 id="sign-detection-heading" className="text-xl font-semibold">
          Sign detection
        </h2>
        <span className={`text-sm font-medium ${STATUS_STYLES[status] ?? 'text-slate-400'}`}
              role="status" aria-live="polite">
          {STATUS_LABELS[status] ?? status}
        </span>
      </header>

      {/* --- server-side problems ------------------------------------- */}
      {serverError && (
        <p className="rounded-lg border border-signal-bad/40 bg-signal-bad/10 p-3 text-sm text-signal-bad"
           role="alert">
          <strong className="font-semibold">{serverError.code}</strong>
          {': '}
          {serverError.message}
        </p>
      )}

      {/* --- which model is doing the work ----------------------------- */}
      {onModeChange && (
        <RecognitionModeToggle
          mode={mode}
          onChange={onModeChange}
          staticModelInfo={modelInfo}
          islModelInfo={islModelInfo}
          dynamicModelInfo={dynamicModelInfo}
        />
      )}

      {/* --- current prediction ---------------------------------------- */}
      <div>
        <div className="flex items-center gap-4">
          <span
            className={`min-w-[3.5rem] text-center text-5xl font-bold tabular-nums ${
              stable ? 'text-signal-ok' : 'text-bridge-400'
            }`}
            aria-hidden="true"
          >
            {showingLetter ? label : '–'}
          </span>

          <div className="flex-1">
            <div
              className="h-6 w-full overflow-hidden rounded-full bg-ink-900"
              role="progressbar"
              aria-valuenow={Math.round(confidence * 100)}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-label="Prediction confidence"
            >
              <div
                className={`h-full transition-[width] duration-100 ${confidenceColour(confidence, stable)}`}
                style={{ width: `${Math.round(confidence * 100)}%` }}
              />
            </div>

            <p className="mt-1 flex justify-between text-sm text-slate-300">
              <span>
                {buffering ? (
                  <>
                    Collecting movement… {bufferFilled}/{bufferLength} frames
                  </>
                ) : showingLetter ? (
                  <>
                    Detecting <strong className="text-slate-100">{label}</strong> at{' '}
                    {(confidence * 100).toFixed(0)}%{stable ? ' — locked on' : ' — settling'}
                  </>
                ) : (
                  'No hand detected — neutral state'
                )}
              </span>
              {latency != null && (
                <span className="tabular-nums text-slate-400">{latency} ms</span>
              )}
            </p>

            {needsBothHands && (
              <p className="mt-1 text-xs text-signal-warn" role="status" aria-live="polite">
                Only one hand visible — most ISL letters need both.
              </p>
            )}
          </div>
        </div>
      </div>

      {/* --- accumulated sentence -------------------------------------- */}
      <div>
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-400">
            Recognised text
          </h3>
          <div className="flex gap-2">
            <button type="button" onClick={onBackspace}
                    className="rounded-md border border-ink-700 px-3 py-1 text-sm hover:bg-ink-700">
              Backspace
            </button>
            <button type="button" onClick={onClear}
                    className="rounded-md border border-ink-700 px-3 py-1 text-sm hover:bg-ink-700">
              Clear
            </button>
          </div>
        </div>

        <p
          className="min-h-[4rem] break-words rounded-lg bg-ink-900 p-4 text-subtitle text-slate-100"
          // polite rather than assertive: new letters should be announced,
          // but must not interrupt whatever the screen reader is already
          // saying mid-conversation.
          aria-live="polite"
          aria-atomic="false"
        >
          {sentence || (
            <span className="text-slate-500">Sign a {unitNoun} to begin…</span>
          )}
        </p>
      </div>

      {/* --- model provenance ------------------------------------------ */}
      {modelInfo && (
        <footer className="border-t border-ink-700 pt-3 text-xs text-slate-400">
          {modelInfo.loaded ? (
            <>
              Model loaded · {modelInfo.classes} classes · validation accuracy{' '}
              {modelInfo.val_accuracy != null
                ? `${(modelInfo.val_accuracy * 100).toFixed(1)}%`
                : 'unknown'}{' '}
              · normalisation v{modelInfo.normalization_version}
            </>
          ) : (
            <>No model loaded on the server. {modelInfo.error}</>
          )}
        </footer>
      )}
    </section>
  );
}
