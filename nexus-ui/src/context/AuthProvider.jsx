import { createContext, useCallback, useEffect, useMemo, useState } from 'react';
import { getToken, saveToken, clearToken } from '../lib/auth.js';
import { setUnauthorizedHandler } from '../lib/api.js';

export const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [token, setToken] = useState(() => getToken());

  // The api.js client calls this whenever a request returns 401 so
  // every component drops back to the login screen automatically.
  useEffect(() => {
    setUnauthorizedHandler(() => {
      clearToken();
      setToken(null);
    });
    return () => setUnauthorizedHandler(null);
  }, []);

  const login = useCallback(async (password) => {
    const res = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password }),
    });
    if (!res.ok) {
      const detail = await res.json().catch(() => ({}));
      const err = new Error(detail.detail || 'Incorrect password');
      err.status = res.status;
      throw err;
    }
    const data = await res.json();
    saveToken(data.token);
    setToken(data.token);
    return data.token;
  }, []);

  const logout = useCallback(() => {
    clearToken();
    setToken(null);
  }, []);

  const value = useMemo(
    () => ({ token, isAuthenticated: !!token, login, logout }),
    [token, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
