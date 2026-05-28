// HTTP client for /api/* routes. Port of the `apiFetch` + `API` helpers
// in rag/static/app.js. Auto-attaches the bearer header, surfaces 401s
// to a global handler so any route guard can react.
//
// Phase 29.2 — apiFetch also injects the active tenant via
// `X-Tenant-ID` on every request that targets a tenant-scoped endpoint,
// reading the id from the provider callback registered by
// TenantProvider. A 403 response (revoked membership, mismatched
// header) routes through the global forbidden-tenant handler so the UI
// can fall back to the workspace picker without each component needing
// to know about tenancy.

import { authHeaders, clearToken } from './auth.js';

let _onUnauthorized = null;
let _onForbiddenTenant = null;
let _tenantIdProvider = null;

// Endpoints that intentionally run WITHOUT a tenant header. These cover
// the pre-selection bootstrap surface: auth + identity + the tenant
// listing the picker itself depends on. Everything else MUST carry a
// tenant id — backend enforces 400 on missing header.
const TENANT_OPTIONAL_PATHS = new Set([
  '/auth/jwt/login',
  '/auth/jwt/logout',
  '/users/me',
  '/tenants',
]);

function shouldInjectTenant(path) {
  if (TENANT_OPTIONAL_PATHS.has(path)) return false;
  // /tenants and /tenants/<id> are both pre-selection (the detail
  // endpoint also accepts the header but tolerates its absence for the
  // listing flow that the picker drives).
  if (path.startsWith('/tenants/')) return false;
  return true;
}

// AuthProvider registers a callback here on mount; api.js calls it on
// any 401 so the provider can flip token state without each component
// needing to know about auth.
export function setUnauthorizedHandler(fn) {
  _onUnauthorized = fn;
}

// TenantProvider registers a callback here on mount; api.js calls it on
// any 403 so the provider can clear active-tenant state and surface the
// picker again.
export function setForbiddenTenantHandler(fn) {
  _onForbiddenTenant = fn;
}

// TenantProvider registers a tenant-id getter here. apiFetch reads it
// once per request and injects `X-Tenant-ID` if a value is available
// and the target path needs one (see TENANT_OPTIONAL_PATHS).
export function setTenantIdProvider(fn) {
  _tenantIdProvider = fn;
}

// Phase 32.1 — expose the active tenant id so non-apiFetch callers
// (notably the SSE stream in sse.js, which manages its own fetch to
// keep the response body raw) can inject `X-Tenant-ID` themselves.
export function getActiveTenantId() {
  return _tenantIdProvider ? _tenantIdProvider() : null;
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

  if (shouldInjectTenant(path) && _tenantIdProvider) {
    const tid = _tenantIdProvider();
    if (tid) init.headers['X-Tenant-ID'] = tid;
  }

  const res = await fetch(`/api${path}`, init);

  if (res.status === 401) {
    clearToken();
    if (_onUnauthorized) _onUnauthorized();
    throw new HTTPError('unauthorized', 401, null);
  }

  if (res.status === 403) {
    // Tenant membership revoked, header/path mismatch, or any other
    // forbidden response on a tenant-scoped route. Let the provider
    // clear local state and bounce the user back to the picker.
    //
    // Phase 31 exception — ``owner_role_required`` means the user IS a
    // valid member of the active tenant, just not an owner. Bouncing
    // them to the picker would be wrong (their tenant is fine; they
    // simply tried to load an admin surface). Let the throw propagate so
    // the calling component can surface a "needs owner" toast without
    // losing the active workspace selection.
    let detail = res.statusText;
    let body = null;
    try {
      body = await res.json();
      detail = body?.detail || detail;
    } catch {
      /* non-JSON */
    }
    if (detail !== 'owner_role_required') {
      if (_onForbiddenTenant) _onForbiddenTenant();
    }
    throw new HTTPError(`403: ${detail}`, 403, detail);
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
