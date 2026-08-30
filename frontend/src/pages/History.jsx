import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import TranscriptDownloadButton from '../components/TranscriptDownloadButton';
import { meetings as meetingsApi } from '../services/api';

/** Past and active meetings the signed-in user hosted or attended. */
export default function History() {
  const [rows, setRows] = useState(null); // null = still loading
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;

    meetingsApi
      .history()
      .then((result) => {
        if (!cancelled) setRows(result);
      })
      .catch((cause) => {
        if (!cancelled) {
          setError(cause.message);
          setRows([]);
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main className="mx-auto max-w-3xl p-6">
      <header className="mb-6 flex items-center justify-between gap-4">
        <h1 className="text-3xl font-bold tracking-tight">Meeting history</h1>
        <Link to="/" className="rounded-lg border border-ink-700 px-3 py-2 text-sm hover:bg-ink-700">
          Back
        </Link>
      </header>

      {error && (
        <p className="mb-4 rounded-lg border border-signal-bad/40 bg-signal-bad/10 p-3 text-sm text-signal-bad"
           role="alert">
          {error}
        </p>
      )}

      {rows === null && <p className="text-slate-400" role="status">Loading…</p>}

      {rows?.length === 0 && !error && (
        // An empty list with no explanation reads as a bug. Say what happened
        // and what to do about it.
        <div className="panel">
          <p className="text-slate-300">You have not been in any meetings yet.</p>
          <Link to="/" className="btn-primary mt-4 inline-block">
            Start one
          </Link>
        </div>
      )}

      <ul className="space-y-3">
        {rows?.map((meeting) => (
          <li key={meeting.id} className="panel flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="font-semibold text-slate-100">{meeting.title}</h2>
              <p className="text-sm text-slate-400">
                <span className="font-mono">{meeting.code}</span>
                {' · hosted by '}
                {meeting.host?.name}
                {' · '}
                {new Date(meeting.created_at).toLocaleString()}
              </p>
            </div>

            <div className="flex items-center gap-3">
              <span
                className={`rounded px-2 py-1 text-xs font-semibold uppercase ${
                  meeting.is_active
                    ? 'bg-signal-ok/20 text-signal-ok'
                    : 'bg-ink-700 text-slate-400'
                }`}
              >
                {meeting.is_active ? 'Active' : 'Ended'}
              </span>

              {/* Offered for ended meetings too — arguably especially for
                  those, since a finished conversation is exactly the one you
                  want a record of. A meeting with no lines still downloads,
                  and the file says so rather than failing. */}
              <TranscriptDownloadButton meetingId={meeting.id} />

              {meeting.is_active && (
                <Link to={`/meeting/${meeting.code}`} className="btn-primary">
                  Rejoin
                </Link>
              )}
            </div>
          </li>
        ))}
      </ul>
    </main>
  );
}
