import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';

import ErrorBoundary from './components/ErrorBoundary';
import { LoadingState, ToastProvider } from './components/ui';
import { AuthProvider, useAuth } from './context/AuthContext';
import History from './pages/History';
import Home from './pages/Home';
import Lobby from './pages/Lobby';
import Login from './pages/Login';
import MeetingEnded from './pages/MeetingEnded';
import MeetingRoom from './pages/MeetingRoom';
import SignDetection from './pages/SignDetection';
import Transcript from './pages/Transcript';

/**
 * Gate for authenticated routes.
 *
 * The `loading` branch matters more than it looks: without it, every page
 * reload flashes the login screen for the moment /api/auth/me is in flight,
 * and a user who *is* signed in gets bounced to Login and back.
 */
function RequireAuth({ children }) {
  const { isAuthenticated, loading } = useAuth();

  if (loading) {
    return (
      <main className="grid min-h-screen place-items-center bg-light-surface">
        <LoadingState message="Loading BridgeTalk…" />
      </main>
    );
  }

  return isAuthenticated ? children : <Navigate to="/login" replace />;
}

/**
 * Login and Register when signed out; Home when already signed in.
 *
 * Returning null rather than a spinner while `loading` is deliberate: this
 * route resolves in a few milliseconds from localStorage, and a spinner that
 * flashes for one frame reads as a glitch.
 */
function PublicOnly({ mode }) {
  const { isAuthenticated, loading } = useAuth();
  if (loading) return null;
  return isAuthenticated ? <Navigate to="/" replace /> : <Login initialMode={mode} />;
}

export default function App() {
  return (
    <ErrorBoundary>
      <AuthProvider>
        <BrowserRouter>
          {/* Inside the router, because a toast for "someone joined" is raised
              from the meeting page; outside the routes, so a toast survives a
              navigation rather than unmounting halfway through its own
              animation. */}
          <ToastProvider>
            <Routes>
              <Route path="/login" element={<PublicOnly mode="login" />} />
              <Route path="/register" element={<PublicOnly mode="register" />} />

              <Route path="/" element={<RequireAuth><Home /></RequireAuth>} />
              <Route path="/history" element={<RequireAuth><History /></RequireAuth>} />

              {/* The transcript page. `/history/:code` rather than
                  `/transcript/:code` because links to it already exist in
                  saved exports and in the review notes. */}
              <Route path="/history/:code" element={<RequireAuth><Transcript /></RequireAuth>} />

              {/* The lobby is the front door: it grants camera/mic permission
                  in a calm screen rather than mid-interview, where the prompt
                  could be counted as a focus violation. */}
              <Route path="/lobby/:code" element={<RequireAuth><Lobby /></RequireAuth>} />
              <Route path="/meeting/:code" element={<RequireAuth><MeetingRoom /></RequireAuth>} />
              <Route path="/ended/:code" element={<RequireAuth><MeetingEnded /></RequireAuth>} />

              {/* The standalone sign-detection screen from Phase 5. It stays
                  because it is the quickest way to check the model is working
                  without needing a second participant. */}
              <Route path="/detect" element={<RequireAuth><SignDetection /></RequireAuth>} />

              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </ToastProvider>
        </BrowserRouter>
      </AuthProvider>
    </ErrorBoundary>
  );
}
