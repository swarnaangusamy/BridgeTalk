import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';

import { AuthProvider, useAuth } from './context/AuthContext';
import Dashboard from './pages/Dashboard';
import History from './pages/History';
import Login from './pages/Login';
import MeetingRoom from './pages/MeetingRoom';
import SignDetection from './pages/SignDetection';

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
      <main className="grid min-h-screen place-items-center">
        <p className="text-slate-300" role="status">
          Loading BridgeTalk…
        </p>
      </main>
    );
  }

  return isAuthenticated ? children : <Navigate to="/login" replace />;
}

function LoginRoute() {
  const { isAuthenticated, loading } = useAuth();
  if (loading) return null;
  return isAuthenticated ? <Navigate to="/" replace /> : <Login />;
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginRoute />} />

          <Route path="/" element={<RequireAuth><Dashboard /></RequireAuth>} />
          <Route path="/history" element={<RequireAuth><History /></RequireAuth>} />
          <Route path="/meeting/:code" element={<RequireAuth><MeetingRoom /></RequireAuth>} />
          {/* The standalone sign-detection screen from Phase 5. It stays
              because it is the quickest way to check the model is working
              without needing a second participant. */}
          <Route path="/detect" element={<RequireAuth><SignDetection /></RequireAuth>} />

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
