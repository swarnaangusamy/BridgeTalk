import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { FormError, Logo, Select, Spinner, TextField } from '../components/ui';
import { useAuth } from '../context/AuthContext';

/**
 * Sign in, or create an account.
 *
 * One component serving two routes rather than two near-identical files. The
 * mode comes from the route (`/login`, `/register`) so the switch link is a
 * real URL that can be bookmarked and that the back button understands, while
 * the shared fields and submit handling stay in one place.
 *
 * VALIDATION HAPPENS IN TWO PLACES ON PURPOSE
 * -------------------------------------------
 * Client-side checks (email shape, password length, passwords matching) exist
 * to give an answer without a round trip, and they are deliberately the SAME
 * rules the server enforces — `UserRegister` sets password min_length=8, so
 * that is the number here too. They are a convenience, not the enforcement:
 * the server validates again and its message wins if the two ever disagree.
 *
 * The specification asks for inline messages under the field, and a single
 * clear message for wrong credentials. Those are different failures and are
 * kept apart: field errors sit under their field, and an authentication
 * failure is one sentence above the button, because "wrong email or password"
 * belongs to neither field by design.
 */
export default function Login({ initialMode = 'login' }) {
  const { login, register } = useAuth();
  const navigate = useNavigate();

  const isRegister = initialMode === 'register';

  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [role, setRole] = useState('deaf');

  const [fieldErrors, setFieldErrors] = useState({});
  const [formError, setFormError] = useState(null);
  const [busy, setBusy] = useState(false);

  function validate() {
    const errors = {};

    if (isRegister && !name.trim()) {
      errors.name = 'Enter your full name';
    }

    if (!email.trim()) {
      errors.email = 'Enter your email';
    } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) {
      errors.email = 'Enter a valid email address';
    }

    if (!password) {
      errors.password = 'Enter your password';
    } else if (isRegister && password.length < 8) {
      // Matches UserRegister's min_length=8 on the server.
      errors.password = 'Use at least 8 characters';
    }

    if (isRegister && confirm !== password) {
      errors.confirm = 'Passwords do not match';
    }

    return errors;
  }

  async function handleSubmit(event) {
    event.preventDefault();
    setFormError(null);

    const errors = validate();
    setFieldErrors(errors);
    if (Object.keys(errors).length > 0) return;

    setBusy(true);
    try {
      if (isRegister) {
        await register({ name: name.trim(), email: email.trim(), password, role });
      } else {
        await login(email.trim(), password);
      }
      // The AuthProvider sets the user; the route guard sends us to Home.
      navigate('/', { replace: true });
    } catch (cause) {
      // A 401 from /login is the one case that deserves the specification's
      // "single clear message" rather than the server's wording, which is
      // phrased for an API consumer.
      setFormError(
        cause?.status === 401
          ? 'Wrong email or password. Try again.'
          : (cause?.message ?? 'Something went wrong. Please try again.'),
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="grid min-h-screen place-items-center bg-light-surface p-4">
      <div className="w-full max-w-authcard">
        <div className="card p-8 shadow-sm">
          <div className="mb-6 flex flex-col items-center gap-3 text-center">
            <Logo to={null} size={32} />
            <h1 className="text-xl font-normal text-light-text">
              {isRegister ? 'Create your account' : 'Sign in to BridgeTalk'}
            </h1>
            <p className="text-sm text-light-muted">
              {isRegister
                ? 'Real-time sign language and speech captions in your video calls.'
                : 'Use your BridgeTalk account to continue'}
            </p>
          </div>

          <form onSubmit={handleSubmit} noValidate className="flex flex-col gap-5">
            {isRegister ? (
              <TextField
                label="Full name"
                value={name}
                onChange={setName}
                error={fieldErrors.name}
                autoComplete="name"
                required
              />
            ) : null}

            <TextField
              label="Email"
              type="email"
              value={email}
              onChange={setEmail}
              error={fieldErrors.email}
              autoComplete="email"
              required
            />

            <TextField
              label="Password"
              type="password"
              value={password}
              onChange={setPassword}
              error={fieldErrors.password}
              hint={isRegister && !fieldErrors.password ? 'At least 8 characters' : undefined}
              autoComplete={isRegister ? 'new-password' : 'current-password'}
              required
            />

            {isRegister ? (
              <>
                <TextField
                  label="Confirm password"
                  type="password"
                  value={confirm}
                  onChange={setConfirm}
                  error={fieldErrors.confirm}
                  autoComplete="new-password"
                  required
                />

                {/* Not cosmetic: the role decides whether sign recognition is
                    pre-selected in the lobby, so a deaf participant does not
                    have to find a toggle before they can be understood. */}
                <Select
                  label="How will you mostly take part?"
                  value={role}
                  onChange={setRole}
                  options={[
                    { value: 'deaf', label: 'I will mostly sign' },
                    { value: 'hearing', label: 'I will mostly speak' },
                  ]}
                  hint="You can change this at any time in a meeting."
                />
              </>
            ) : null}

            <FormError>{formError}</FormError>

            <button type="submit" disabled={busy} className="btn-primary h-11 w-full">
              {busy ? (
                <>
                  <Spinner size={16} className="border-white/40 border-t-white" />
                  {isRegister ? 'Creating account…' : 'Signing in…'}
                </>
              ) : isRegister ? (
                'Create account'
              ) : (
                'Sign in'
              )}
            </button>
          </form>
        </div>

        <p className="mt-6 text-center text-sm text-light-muted">
          {isRegister ? 'Already have an account? ' : 'New to BridgeTalk? '}
          <Link
            to={isRegister ? '/login' : '/register'}
            className="font-medium text-light-blue hover:underline"
          >
            {isRegister ? 'Sign in' : 'Create an account'}
          </Link>
        </p>
      </div>
    </main>
  );
}
