import { useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import TranscriptDownloadButton from '../components/TranscriptDownloadButton';
import { meetings as meetingsApi, transcripts as transcriptsApi } from '../services/api';

/**
 * One past meeting: its details, participants, and the full transcript.
 *
 * Reached from the history list. Keyed by meeting CODE rather than id, so the
 * URL is the same thing the host read out during the meeting and the existing
 * `GET /api/meetings/{code}` endpoint can serve the header without a new route.
 *
 * Access control is NOT enforced here. The transcript endpoint is member-only
 * on the server, so a non-participant opening this URL gets an error from the
 * API rather than a page that merely hides the content.
 */
export default function MeetingDetail() {
  const { code } = useParams();

  const [meeting, setMeeting] = useState(null);
  const [lines, setLines] = useState(null); // null = still loading
  const [error, setError] = useState(null);
  const [query, setQuery] = useState('');

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const found = await meetingsApi.get(code);
        if (cancelled) return;
        setMeeting(found);

        const rows = await transcriptsApi.list(found.id);
        if (cancelled) return;
        setLines(rows);
      } catch (cause) {
        if (cancelled) return;
        setError(cause.message ?? 'Could not load this meeting');
        setLines([]);
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [code]);

  // Search is client-side on purpose: a transcript is at most a few hundred
  // lines, already in memory, and filtering locally means results appear as
  // you type with no request per keystroke.
  const filtered = useMemo(() => {
    if (!lines) return null;
    const needle = query.trim().toLowerCase();
    if (!needle) return lines;
    return lines.filter(
      (line) =>
        line.content.toLowerCase().includes(needle) ||
        (line.user_name ?? '').toLowerCase().includes(needle),
    );
  }, [lines, query]);

  const duration = useMemo(() => {
    if (!meeting?.started_at) return null;
    const end = meeting.ended_at ? new Date(meeting.ended_at) : new Date();
    const seconds = Math.max(0, Math.round((end - new Date(meeting.started_at)) / 1000));
    const minutes = Math.floor(seconds / 60);
    return `${minutes}m ${String(seconds % 60).padStart(2, '0')}s`;
  }, [meeting]);

  return (
    <main className="mx-auto max-w-4xl p-6">
      <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">
            {meeting?.title ?? 'Meeting'}
          </h1>
          <p className="mt-1 text-sm text-slate-400">
            <span className="font-mono">{code}</span>
            {meeting?.host?.name && <> · hosted by {meeting.host.name}</>}
            {meeting?.started_at && (
              <> · {new Date(meeting.started_at).toLocaleString()}</>
            )}
            {duration && <> · {duration}</>}
            {meeting?.is_interview_mode && (
              <span className="ml-2 rounded bg-signal-warn/20 px-2 py-0.5 text-xs font-semibold uppercase text-signal-warn">
                Interview mode
              </span>
            )}
          </p>
        </div>

        <div className="flex items-center gap-2">
          {meeting?.id && (
            <>
              <TranscriptDownloadButton meetingId={meeting.id} format="txt" />
              <TranscriptDownloadButton meetingId={meeting.id} format="pdf" />
            </>
          )}
          <Link
            to="/history"
            className="rounded-lg border border-ink-700 px-3 py-2 text-sm hover:bg-ink-700"
          >
            Back
          </Link>
        </div>
      </header>

      {error && (
        <p
          className="mb-4 rounded-lg border border-signal-bad/40 bg-signal-bad/10 p-3 text-sm text-signal-bad"
          role="alert"
        >
          {error}
        </p>
      )}

      {/* --- participants ------------------------------------------------ */}
      {meeting?.participants?.length > 0 && (
        <section className="panel mb-4" aria-labelledby="participants-heading">
          <h2
            id="participants-heading"
            className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-400"
          >
            Participants
          </h2>
          <ul className="flex flex-wrap gap-2">
            {meeting.participants.map((participant) => (
              <li
                key={participant.id}
                className="rounded-md border border-ink-700 bg-ink-900 px-2 py-1 text-sm text-slate-200"
              >
                {participant.user?.name ?? 'Unknown participant'}
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* --- search ------------------------------------------------------ */}
      <div className="mb-3">
        <label htmlFor="transcript-search" className="sr-only">
          Search the transcript
        </label>
        <input
          id="transcript-search"
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search this transcript…"
          className="w-full rounded-lg border border-ink-700 bg-ink-900 px-3 py-2 text-slate-100 placeholder:text-slate-500"
        />
        {query && filtered && (
          <p className="mt-1 text-xs text-slate-400" role="status" aria-live="polite">
            {filtered.length} of {lines.length} lines match “{query}”
          </p>
        )}
      </div>

      {/* --- transcript -------------------------------------------------- */}
      {lines === null && !error && (
        <p className="text-slate-400" role="status">
          Loading transcript…
        </p>
      )}

      {lines?.length === 0 && !error && (
        <div className="panel">
          <p className="text-slate-300">
            No transcript was recorded for this meeting.
          </p>
          <p className="mt-1 text-sm text-slate-500">
            Captions are saved as they are recognised, so a meeting nobody
            signed or spoke in has nothing to show.
          </p>
        </div>
      )}

      {filtered?.length === 0 && lines?.length > 0 && (
        <p className="panel text-slate-300">Nothing in this transcript matches “{query}”.</p>
      )}

      {filtered?.length > 0 && (
        <ol className="space-y-3">
          {filtered.map((line) => (
            <li key={line.id} className="panel border-l-2 border-ink-700">
              <p className="flex flex-wrap items-center gap-2 text-xs text-slate-400">
                <span
                  className={`rounded px-1.5 py-0.5 font-semibold uppercase ${
                    line.source === 'sign'
                      ? 'bg-bridge-500/20 text-bridge-400'
                      : 'bg-signal-ok/20 text-signal-ok'
                  }`}
                >
                  {line.source === 'sign' ? '🤟 sign' : '🎤 speech'}
                </span>
                <span className="font-medium text-slate-300">{line.user_name}</span>
                <time dateTime={line.created_at}>
                  {new Date(line.created_at).toLocaleTimeString()}
                </time>
                {line.confidence != null && (
                  <span className="tabular-nums">
                    {(line.confidence * 100).toFixed(0)}%
                  </span>
                )}
              </p>
              <p className="mt-1 break-words text-slate-100">{line.content}</p>
            </li>
          ))}
        </ol>
      )}
    </main>
  );
}
