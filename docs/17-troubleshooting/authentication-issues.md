# Authentication Issues

---

## 401 Unauthorized

| Symptom | Cause | Fix |
|---|---|---|
| All API requests return `401` | Token expired (3600s lifetime) | Re-login: `POST /api/auth/login` |
| Token obtained but `401` on use | `Authorization: Bearer` header missing or malformed | Verify header: `Authorization: Bearer <token>` (no quotes around token) |
| `401` after server restart | `JWT_SECRET` changed | Expected — all tokens invalidated; re-login |
| API token returns `401` | Token revoked or wrong `nxs_` prefix | Check token exists: `GET /api/tokens`; regenerate if missing |

---

## 403 Forbidden

| Error detail | Cause | Fix |
|---|---|---|
| `"Manager role required"` | Caller is `member`, endpoint needs `admin+` | Request admin promotion from workspace owner |
| `"Owner role required"` | Caller is `admin`, endpoint needs `owner` | Contact workspace owner |
| `"Workspace is archived"` | Workspace archived | Owner must call `POST /api/tenants/{id}/unarchive` |
| `"Token scope insufficient"` | API token lacks required scope | Revoke + recreate token with correct scope |

---

## Tenant Auth Failures

```bash
# Verify tenant resolution
curl https://chat.nexus.gayo-sphere.cloud/api/tenants \
  -H "Authorization: Bearer $TOKEN" | jq '.[].slug'
```

| Symptom | Cause | Fix |
|---|---|---|
| `404` on tenant-scoped endpoint | Wrong `tenant_id` in request | Verify UUID from `GET /api/tenants` |
| `403` on correct tenant | User not a member of that tenant | Check membership: `GET /api/tenants/{id}/members` |
| Chat returns `403` | No active workspace or workspace archived | Unarchive or create workspace |

---

## JWT Secret Rotation Side Effects

After changing `JWT_SECRET`:
- All existing JWTs are immediately invalid
- All users must re-login
- API tokens (stored as SHA-256 hashes) are **not** affected — they continue to work

---

## First Superuser Creation

If login returns `401` and no users exist:

```bash
ssh nexus-rag@72.62.196.231
cd /home/nexus-rag/rag
uv run python -m rag.scripts.create_superuser
```

---

## API Token Issues

```bash
# List active tokens
curl https://chat.nexus.gayo-sphere.cloud/api/tokens \
  -H "Authorization: Bearer $JWT_TOKEN"

# Token value only shown at creation — cannot retrieve later
# If lost: revoke + regenerate
curl -X DELETE https://chat.nexus.gayo-sphere.cloud/api/tokens/{token_id} \
  -H "Authorization: Bearer $JWT_TOKEN"
```

---

## Related Docs

- [JWT Authentication](../05-authentication/jwt-authentication.md)
- [API Tokens](../05-authentication/api-tokens.md)
- [RBAC Enforcement](../05-authentication/rbac-enforcement.md)
