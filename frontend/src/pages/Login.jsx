import { useState } from 'react';

import { useAuth } from '../context/AuthContext';

/**
 * Sign in, or create an account.
 *
 * One form with a mode toggle rather than two pages: it is less code, and it
 * removes the "wrong page" dead end where someone types their details into
 * Login when they have never registered.
 */
export default function Login() {
  const { login, register } = useAuth();

  const [mode, setMode] = useState('login'); // login | register
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [role, setRole] = useState('deaf');
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const isRegister = mode === 'register';

  async function handleSubmit(event) {
    event.preventDefault();
    setError(null);
    setBusy(true);

    try {
      if (isRegister) {
        await register({ name, email, password, role });
      } else {
        await login(email, password);
      }
      // On success the AuthProvider sets the user and App swaps the route —
      // nothing to do here.
    } catch (cause) {
      setError(cause.message);
    } finally {
      setBusy(false);
    }
  }

  function fillDemoAccount() {
    setMode('login');
    setEmail('deaf.demo@example.com');
    setPassword('bridgetalk123');
    setError(null);
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center gap-6 p-6">
      <header>
        <h1 className="text-4xl font-bold tracking-tight">BridgeTalk</h1>
        <p className="mt-2 text-slate-300">
          Real-time sign language to text, for deaf and hearing participants.
        </p>
      </header>

      <form onSubmit={handleSubmit} className="panel flex flex-col gap-4">
        <h2 className="text-xl font-semibold">{isRegister ? 'Create an account' : 'Sign in'}</h2>

        {error && (
          <p className="rounded-lg border border-signal-bad/40 bg-signal-bad/10 p-3 text-sm text-signal-bad"
             role="alert">
            {error}
          </p>
        )}

        {isRegister && (
          <label className="flex flex-col gap-1">
            <span className="text-sm font-medium text-slate-200">Name</span>
            <input
              type="text" required value={name} onChange={(e) => setName(e.target.value)}
              autoComplete="name"
              className="rounded-lg border border-ink-700 bg-ink-900 px-3 py-2 text-slate-100"
            />
          </label>
        )}

        <label className="flex flex-col gap-1">
          <span className="text-sm font-medium text-slate-200">Email</span>
          <input
            type="email" required value={email} onChange={(e) => setEmail(e.target.value)}
            autoComplete="email"
            className="rounded-lg border border-ink-700 bg-ink-900 px-3 py-2 text-slate-100"
          />
        </label>

        <label className="flex flex-col gap-1">
          <span className="text-sm font-medium text-slate-200">Password</span>
          <input
            type="password" required minLength={isRegister ? 8 : undefined}
            value={password} onChange={(e) => setPassword(e.target.value)}
            autoComplete={isRegister ? 'new-password' : 'current-password'}
            className="rounded-lg border border-ink-700 bg-ink-900 px-3 py-2 text-slate-100"
          />
          {isRegister && (
            <span className="text-xs text-slate-400">At least 8 characters.</span>
          )}
        </label>

        {isRegister && (
          <fieldset className="flex flex-col gap-2">
            <legend className="text-sm font-medium text-slate-200">I am</legend>
            {/* A UI hint, not a permission boundary — both roles can use both
                translation directions. */}
            {[
              ['deaf', 'Deaf or hard of hearing — I sign'],
              ['hearing', 'Hearing — I speak'],
            ].map(([value, labelText]) => (
              <label key={value} className="flex items-center gap-2 text-sm text-slate-200">
                <input
                  type="radio" name="role" value={value}
                  checked={role === value} onChange={() => setRole(value)}
                />
                {labelText}
              </label>
            ))}
          </fieldset>
        )}

        <button type="submit" disabled={busy} className="btn-primary mt-2">
          {busy ? 'Please wait…' : isRegister ? 'Create account' : 'Sign in'}
        </button>

        <p className="text-sm text-slate-300">
          {isRegister ? 'Already have an account?' : 'No account yet?'}{' '}
          <button
            type="button"
            onClick={() => { setMode(isRegister ? 'login' : 'register'); setError(null); }}
            className="font-semibold text-bridge-400 underline"
          >
            {isRegister ? 'Sign in' : 'Create one'}
          </button>
        </p>
      </form>

      <button type="button" onClick={fillDemoAccount}
              className="text-sm text-slate-400 underline hover:text-slate-200">
        Use the seeded demo account
      </button>
    </main>
  );
}
