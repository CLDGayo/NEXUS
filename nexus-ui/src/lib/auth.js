// Auth token storage helpers. Mirrors the legacy `Auth` object in
// rag/static/app.js so the FastAPI backend cannot tell the difference
// between the vanilla SPA and the React port:
//   - JWT lives in localStorage under `nexus_token`.
//   - Every authed request carries `Authorization: Bearer <token>`.

export const TOKEN_KEY = 'nexus_token';

export function getToken() {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    // Some embedded contexts (iframes with strict storage policies)
    // throw on localStorage access. Treat as logged-out.
    return null;
  }
}

export function saveToken(token) {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

export function authHeaders(extra) {
  const token = getToken();
  const base = { 'Content-Type': 'application/json', ...(extra || {}) };
  if (token) base.Authorization = `Bearer ${token}`;
  return base;
}
