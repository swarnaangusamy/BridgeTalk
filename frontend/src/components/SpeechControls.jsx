import { LANGUAGES, PROVIDERS } from '../services/stt';

/**
 * Provider selector, language selector and live status for speech captions.
 *
 * WHY THE STATUS LINE MATTERS
 * ---------------------------
 * The two providers behave visibly differently — one streams partial words,
 * the other produces nothing until you stop talking. Without a status line
 * saying which is running, "Whisper is thinking" and "captions are broken"
 * look identical, and the user has no way to tell them apart.
 *
 * The engine is switchable here without reloading: the hook rebuilds the
 * provider underneath and the caption bar never knows.
 */
export default function SpeechControls({
  enabled,
  onToggle,
  providerId,
  onProviderChange,
  language,
  onLanguageChange,
  state,
  providerName,
  providerNote,
  providesInterim,
  notice,
  error,
}) {
  const statusWord =
    state === 'listening'
      ? 'listening'
      : state === 'error'
        ? 'error'
        : state === 'unsupported'
          ? 'unavailable'
          : 'idle';

  return (
    <section
      className="rounded-xl border border-ink-700 bg-ink-800 p-4"
      aria-labelledby="speech-controls-heading"
    >
      <header className="mb-3 flex items-center justify-between gap-3">
        <h3
          id="speech-controls-heading"
          className="text-sm font-semibold uppercase tracking-wide text-slate-400"
        >
          Speech captions
        </h3>
        <button
          type="button"
          onClick={onToggle}
          aria-pressed={enabled}
          className={`rounded-md border px-3 py-1 text-sm font-medium ${
            enabled
              ? 'border-signal-ok/50 bg-signal-ok/15 text-signal-ok'
              : 'border-ink-700 bg-ink-900 text-slate-300 hover:bg-ink-700'
          }`}
        >
          {enabled ? 'On' : 'Off'}
        </button>
      </header>

      <div className="grid gap-3 sm:grid-cols-2">
        <label className="flex flex-col gap-1 text-xs text-slate-400">
          Engine
          <select
            value={providerId ?? ''}
            onChange={(event) => onProviderChange(event.target.value)}
            className="rounded-md border border-ink-700 bg-ink-900 px-2 py-1.5 text-sm text-slate-100"
          >
            {Object.values(PROVIDERS).map((entry) => (
              <option key={entry.id} value={entry.id}>
                {entry.label}
              </option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1 text-xs text-slate-400">
          Language
          <select
            value={language}
            onChange={(event) => onLanguageChange(event.target.value)}
            className="rounded-md border border-ink-700 bg-ink-900 px-2 py-1.5 text-sm text-slate-100"
          >
            {LANGUAGES.map((entry) => (
              <option key={entry.code} value={entry.code}>
                {entry.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      <p
        className="mt-3 flex items-center gap-2 text-xs text-slate-300"
        role="status"
        aria-live="polite"
      >
        <span
          className={`inline-block h-2 w-2 rounded-full ${
            state === 'listening'
              ? 'animate-pulse bg-signal-ok'
              : state === 'error' || state === 'unsupported'
                ? 'bg-signal-bad'
                : 'bg-slate-600'
          }`}
          aria-hidden="true"
        />
        <span>
          {providerName} · {language} · {statusWord}
        </span>
      </p>

      {/* Whisper produces no partial text, so say so rather than letting the
          caption bar look frozen while somebody is mid-sentence. */}
      {enabled && !providesInterim && state === 'listening' && (
        <p className="mt-2 text-xs text-slate-400">
          This engine captions whole sentences, so nothing appears until you pause.
        </p>
      )}

      {providerNote && <p className="mt-2 text-xs text-slate-500">{providerNote}</p>}

      {notice && (
        <p
          className="mt-2 rounded-lg border border-signal-warn/40 bg-signal-warn/10 p-2 text-xs text-slate-200"
          role="status"
        >
          {notice}
        </p>
      )}

      {error && (
        <p
          className="mt-2 rounded-lg border border-signal-bad/40 bg-signal-bad/10 p-2 text-xs text-signal-bad"
          role="alert"
        >
          {error}
        </p>
      )}

      {/* PROBLEM: echo. getUserMedia's echoCancellation helps but does not
          fully solve a laptop speaker feeding its own microphone. */}
      <p className="mt-2 text-xs text-slate-500">
        🎧 Headphones recommended — otherwise the microphone may caption the other
        participant’s voice as yours.
      </p>
    </section>
  );
}
