import { createContext, useCallback, useEffect, useMemo, useState } from 'react';
import { getToken, saveToken, clearToken } from '../lib/auth.js';
import { setUnauthorizedHandler } from '../lib/api.js';

export const AuthContext = createContext(null);

// fastapi-users error codes (rag/auth) → human-readable copy. Anything not
// listed falls through to the raw `detail` string so future codes are still
// surfaced rather than swallowed.
const LOGIN_ERROR_COPY = {
  LOGIN_BAD_CREDENTIALS: 'Incorrect email or password.',
  LOGIN_USER_NOT_VERIFIED: 'Account not verified. Contact an administrator.',
};

function readErrorDetail(payload) {
  const raw = payload && payload.detail;
  if (typeof raw === 'string') return LOGIN_ERROR_COPY[raw] || raw;
  if (raw && typeof raw === 'object' && typeof raw.code === 'string') {
    return LOGIN_ERROR_COPY[raw.code] || raw.reason || raw.code;
  }
  return 'Login failed.';
}

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

  const login = useCallback(async (email, password) => {
    // fastapi-users expects OAuth2PasswordRequestForm — application/x-www-form-urlencoded
    // with `username` + `password` keys. Email is the username.
    const body = new URLSearchParams();
    body.set('username', email);
    body.set('password', password);

    const res = await fetch('/api/auth/jwt/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: body.toString(),
    });
    if (!res.ok) {
      const detail = await res.json().catch(() => ({}));
      const err = new Error(readErrorDetail(detail));
      err.status = res.status;
      throw err;
    }
    const data = await res.json();
    saveToken(data.access_token);
    setToken(data.access_token);
    return data.access_token;
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
