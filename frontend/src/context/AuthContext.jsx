import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';

import { ApiError, auth as authApi, clearToken, getToken, setToken } from '../services/api';

const AuthContext = createContext(null);

/**
 * Holds the signed-in user for the whole app.
 *
 * On mount it calls /api/auth/me with any stored token. That round trip is the
 * point: a token in localStorage proves only that someone logged in once, not
 * that the token is still valid. It may have expired, or been signed with a
 * secret the server has since rotated. Asking the server is the only way to
 * know, and it means a stale token logs the user out cleanly instead of
 * producing a dashboard where every request 401s.
 */
export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function restoreSession() {
      if (!getToken()) {
        setLoading(false);
        return;
      }

      try {
        const profile = await authApi.me();
        if (!cancelled) setUser(profile);
      } catch (error) {
        // 401 means the token is genuinely dead — discard it. Any other
        // failure (the backend being down, say) should NOT throw away a
        // perfectly good token; the user can retry once the server is back.
        if (error instanceof ApiError && error.status === 401) {
          clearToken();
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    restoreSession();
    // Guards against setting state after unmount in React 18 StrictMode, which
    // deliberately mounts effects twice in development.
    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(async (email, password) => {
    const result = await authApi.login(email, password);
    setToken(result.access_token);
    setUser(result.user);
    return result.user;
  }, []);

  const register = useCallback(async (payload) => {
    const result = await authApi.register(payload);
    setToken(result.access_token);
    setUser(result.user);
    return result.user;
  }, []);

  const logout = useCallback(() => {
    clearToken();
    setUser(null);
  }, []);

  const value = useMemo(
    () => ({ user, loading, login, register, logout, isAuthenticated: user !== null }),
    [user, loading, login, register, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === null) {
    throw new Error('useAuth must be used inside an <AuthProvider>');
  }
  return context;
}
