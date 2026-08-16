import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { useAuth } from '../context/AuthContext';
import { meetings as meetingsApi } from '../services/api';

/**
 * Start a meeting, or join one with a code.
 *
 * The created code is shown before navigating away, because the host has to be
 * able to read it out or paste it to the other participant. Redirecting
 * straight into the room would hide the one piece of information they need.
 */
export default function Dashboard() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const [title, setTitle] = useState('BridgeTalk meeting');
  const [interviewMode, setInterviewMode] = useState(false);
  const [joinCode, setJoinCode] = useState('');
  const [created, setCreated] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function handleCreate(event) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      setCreated(await meetingsApi.create(title, interviewMode));
    } catch (cause) {
      setError(cause.message);
    } finally {
      setBusy(false);
    }
  }

  async function handleJoin(event) {
    event.preventDefault();
    setError(null);
    const code = joinCode.trim().toUpperCase();
    if (!code) return;

    setBusy(true);
    try {
      // Check the meeting exists before navigating, so a typo produces a clear
      // message here rather than a room that fails to load.
      await meetingsApi.get(code);
      navigate(`/meeting/${encodeURIComponent(code)}`);
    } catch (cause) {
      setError(cause.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto max-w-3xl p-6">
      <header className="mb-8 flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">BridgeTalk</h1>
          <p className="mt-1 text-slate-300">
            Signed in as {user?.name} ({user?.role})
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Link to="/history"
                className="rounded-lg border border-ink-700 px-3 py-2 text-sm hover:bg-ink-700">
            History
          </Link>
          <Link to="/detect"
                className="rounded-lg border border-ink-700 px-3 py-2 text-sm hover:bg-ink-700">
            Test sign detection
          </Link>
          <button type="button" onClick={logout}
                  className="rounded-lg border border-ink-700 px-3 py-2 text-sm hover:bg-ink-700">
            Log out
          </button>
        </div>
      </header>

      {error && (
        <p className="mb-6 rounded-lg border border-signal-bad/40 bg-signal-bad/10 p-3 text-sm text-signal-bad"
           role="alert">
          {error}
        </p>
      )}

      <div className="grid gap-6 sm:grid-cols-2">
        {/* --- create ------------------------------------------------- */}
        <form onSubmit={handleCreate} className="panel flex flex-col gap-4">
          <h2 className="text-xl font-semibold">Start a meeting</h2>

          <label className="flex flex-col gap-1">
            <span className="text-sm font-medium text-slate-200">Title</span>
            <input
              type="text" required value={title} onChange={(e) => setTitle(e.target.value)}
              className="rounded-lg border border-ink-700 bg-ink-900 px-3 py-2 text-slate-100"
            />
          </label>

          <label className="flex items-start gap-2 text-sm text-slate-200">
            <input
              type="checkbox"
              checked={interviewMode}
              onChange={(e) => setInterviewMode(e.target.checked)}
              className="mt-1"
            />
            <span>
              Interview Mode
              <span className="block text-xs text-slate-400">
                Logs when a participant switches away from the tab. A deterrent,
                not proctoring — it cannot see other devices or the room.
              </span>
            </span>
          </label>

          <button type="submit" disabled={busy} className="btn-primary">
            Create meeting
          </button>

          {created && (
            <div className="rounded-lg border border-bridge-500/40 bg-bridge-500/10 p-4">
              <p className="text-sm text-slate-300">Share this code:</p>
              <p className="my-2 font-mono text-3xl font-bold tracking-widest text-bridge-400">
                {created.code}
              </p>
              <Link to={`/meeting/${created.code}`} className="btn-primary inline-block">
                Enter the meeting
              </Link>
            </div>
          )}
        </form>

        {/* --- join --------------------------------------------------- */}
        <form onSubmit={handleJoin} className="panel flex flex-col gap-4">
          <h2 className="text-xl font-semibold">Join a meeting</h2>

          <label className="flex flex-col gap-1">
            <span className="text-sm font-medium text-slate-200">Meeting code</span>
            <input
              type="text"
              value={joinCode}
              onChange={(e) => setJoinCode(e.target.value.toUpperCase())}
              placeholder="ABC-123"
              // Codes never contain O, I, L, 0 or 1, so no character here is
              // ambiguous when read aloud.
              className="rounded-lg border border-ink-700 bg-ink-900 px-3 py-2 font-mono text-lg uppercase tracking-widest text-slate-100"
              autoCapitalize="characters"
              autoComplete="off"
            />
          </label>

          <button type="submit" disabled={busy || !joinCode.trim()} className="btn-primary">
            Join
          </button>

          <p className="text-xs text-slate-400">
            Codes never contain the letters O, I or L, or the digits 0 and 1 — so
            there is nothing ambiguous to mistype.
          </p>
        </form>
      </div>
    </main>
  );
}
