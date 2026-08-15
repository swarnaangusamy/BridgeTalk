import { useCallback, useEffect, useState } from 'react';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';

/**
 * Phase 0 shell.
 *
 * This is deliberately small but real: it calls the backend's /health endpoint
 * so that "frontend and backend are both up and can talk to each other" is
 * something you can *see*, not something you assume. It also proves the CORS
 * configuration works before any authentication is layered on top.
 *
 * Phases 1-7 replace this component with the router (Login, Register,
 * Dashboard, MeetingRoom, History).
 */
export default function App() {
  // 'checking' | 'online' | 'offline'
  const [status, setStatus] = useState('checking');
  const [detail, setDetail] = useState('');

  const checkHealth = useCallback(async () => {
    setStatus('checking');
    setDetail('');
    try {
      const response = await fetch(`${API_BASE_URL}/health`);
      if (!response.ok) {
        throw new Error(`Backend replied ${response.status}`);
      }
      const body = await response.json();
      setStatus('online');
      setDetail(JSON.stringify(body));
    } catch (error) {
      // A failed fetch here is almost always one of three things: the backend
      // is not running, it is on a different port, or CORS is misconfigured.
      // Say so instead of showing a bare "Failed to fetch".
      setStatus('offline');
      setDetail(error.message);
    }
  }, []);

  useEffect(() => {
    checkHealth();
  }, [checkHealth]);

  const statusStyles = {
    checking: 'text-signal-warn',
    online: 'text-signal-ok',
    offline: 'text-signal-bad',
  };

  const statusLabels = {
    checking: 'Checking…',
    online: 'Online',
    offline: 'Offline',
  };

  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col justify-center gap-6 p-6">
      <header>
        <h1 className="text-4xl font-bold tracking-tight">BridgeTalk</h1>
        <p className="mt-2 text-lg text-slate-300">
          Real-time sign language to text translation for deaf and hearing
          participants in a video call.
        </p>
      </header>

      <section className="panel" aria-labelledby="backend-status-heading">
        <h2 id="backend-status-heading" className="text-xl font-semibold">
          Backend status
        </h2>

        <p className="mt-3 flex items-baseline gap-3">
          <span className="text-slate-300">{API_BASE_URL}/health</span>
          <span
            className={`font-semibold ${statusStyles[status]}`}
            role="status"
            aria-live="polite"
          >
            {statusLabels[status]}
          </span>
        </p>

        {detail && (
          <pre className="mt-3 overflow-x-auto rounded-lg bg-ink-900 p-3 text-sm text-slate-300">
            {detail}
          </pre>
        )}

        {status === 'offline' && (
          <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-slate-300">
            <li>
              Start the API with <code>./scripts/run_backend.sh</code> (Windows:{' '}
              <code>scripts\run_backend.bat</code>).
            </li>
            <li>
              Confirm <code>VITE_API_BASE_URL</code> in <code>.env</code> matches
              the port Uvicorn printed.
            </li>
            <li>
              Confirm this origin is listed in <code>CORS_ORIGINS</code>.
            </li>
          </ul>
        )}

        <button type="button" onClick={checkHealth} className="btn-primary mt-4">
          Check again
        </button>
      </section>

      <footer className="text-sm text-slate-400">
        Phase 0 — scaffold. MCA mini project, PSG College of Technology.
      </footer>
    </main>
  );
}
