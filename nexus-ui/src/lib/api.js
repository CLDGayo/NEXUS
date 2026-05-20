// HTTP client for /api/* routes. Port of the `apiFetch` + `API` helpers
// in rag/static/app.js. Auto-attaches the bearer header, surfaces 401s
// to a global handler so any route guard can react.

import { authHeaders, clearToken } from './auth.js';

let _onUnauthorized = null;

// AuthProvider registers a callback here on mount; api.js calls it on
// any 401 so the provider can flip token state without each component
// needing to know about auth.
export function setUnauthorizedHandler(fn) {
  _onUnauthorized = fn;
}

class HTTPError extends Error {
  constructor(message, status, body) {
    super(message);
    this.name = 'HTTPError';
    this.status = status;
    this.body = body;
  }
}

async function apiFetch(path, opts = {}) {
  const { headers, body, json, ...rest } = opts;

  // If `json` was passed, JSON-stringify it. Otherwise pass `body`
  // through untouched (e.g. FormData for uploads).
  const init = {
    ...rest,
    headers: { ...authHeaders(), ...(headers || {}) },
  };
  if (json !== undefined) {
    init.body = JSON.stringify(json);
  } else if (body !== undefined) {
    init.body = body;
    // FormData must not carry the JSON content-type — let the browser
    // set the multipart boundary.
    if (body instanceof FormData) delete init.headers['Content-Type'];
  }

  const res = await fetch(`/api${path}`, init);

  if (res.status === 401) {
    clearToken();
    if (_onUnauthorized) _onUnauthorized();
    throw new HTTPError('unauthorized', 401, null);
  }

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = data.detail || detail;
    } catch {
      /* non-JSON body — keep statusText */
    }
    throw new HTTPError(`${res.status}: ${detail}`, res.status, detail);
  }

  if (res.status === 204) return null;
  const ct = res.headers.get('content-type') || '';
  if (ct.includes('application/json')) return res.json();
  return res.text();
}

export const api = {
  get: (path) => apiFetch(path),
  post: (path, json) => apiFetch(path, { method: 'POST', json }),
  patch: (path, json) => apiFetch(path, { method: 'PATCH', json }),
  put: (path, json) => apiFetch(path, { method: 'PUT', json }),
  del: (path) => apiFetch(path, { method: 'DELETE' }),
  upload: (path, formData) => apiFetch(path, { method: 'POST', body: formData }),
  raw: apiFetch,
};

export { HTTPError };
