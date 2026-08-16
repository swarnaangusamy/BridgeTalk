import { AuthProvider, useAuth } from './context/AuthContext';
import Login from './pages/Login';
import SignDetection from './pages/SignDetection';

/**
 * Phase 5 shell: sign in, then the sign-detection screen.
 *
 * Routing is deliberately a single conditional rather than react-router. There
 * are exactly two screens at this phase, and a router with two routes is
 * indirection without benefit. Phase 6 introduces Dashboard, MeetingRoom and
 * History, at which point the router earns its place.
 */
function AppRoutes() {
  const { isAuthenticated, loading } = useAuth();

  // Without this branch the app flashes the login form for a moment on every
  // reload while /api/auth/me is in flight, which looks like being logged out.
  if (loading) {
    return (
      <main className="grid min-h-screen place-items-center">
        <p className="text-slate-300" role="status">
          Loading BridgeTalk…
        </p>
      </main>
    );
  }

  return isAuthenticated ? <SignDetection /> : <Login />;
}

export default function App() {
  return (
    <AuthProvider>
      <AppRoutes />
    </AuthProvider>
  );
}
