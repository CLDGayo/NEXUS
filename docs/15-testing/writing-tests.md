# Writing Tests

Patterns, fixtures, and anti-patterns for writing NEXUS tests.

---

## Basic Async Test

```python
# No decorator needed — asyncio_mode = auto
async def test_rrf_empty_inputs():
    result = reciprocal_rank_fusion([], [], k=60)
    assert result == []
```

---

## Using DB Fixtures

```python
@pytest.mark.integration
async def test_create_tenant(db_session, user_fixture):
    tenant = Tenant(name="Test Corp", slug="test-corp", owner_id=user_fixture.id)
    db_session.add(tenant)
    await db_session.commit()

    fetched = await db_session.get(Tenant, tenant.id)
    assert fetched.slug == "test-corp"
```

`db_session` is automatically rolled back after each test — no cleanup needed.

---

## Fake Redis

Use `fakeredis` for tests that touch Redis. Never hit a real Redis in unit tests.

```python
import fakeredis.aioredis

@pytest.fixture
async def redis_client():
    return fakeredis.aioredis.FakeRedis()

async def test_hitl_pause_key(redis_client):
    from rag.messenger.hitl import set_hitl_pause

    await set_hitl_pause(redis_client, sender_id="psid-123", ttl=3600)
    assert await redis_client.exists("hitl:psid-123")
```

---

## Moto S3 (MinIO)

Mock S3-compatible calls with `moto`:

```python
import boto3
from moto import mock_aws

@mock_aws
async def test_avatar_upload():
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="nexus-avatars")

    from rag.routers.tenants import upload_avatar
    url = await upload_avatar(tenant_slug="acme", file_bytes=b"...", content_type="image/webp")
    assert "nexus-avatars" in url
```

---

## FastAPI Test Client

Use `httpx.AsyncClient` for router tests:

```python
from httpx import AsyncClient
from rag.app import app

@pytest.mark.integration
async def test_health_endpoint():
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
```

---

## Auth Headers

```python
async def test_list_members_requires_auth(client):
    response = await client.get("/api/tenants/123/members")
    assert response.status_code == 401

async def test_list_members_as_member_forbidden(client, member_token):
    response = await client.get(
        "/api/tenants/123/members",
        headers={"Authorization": f"Bearer {member_token}"}
    )
    assert response.status_code == 403

async def test_list_members_as_admin(client, admin_token):
    response = await client.get(
        "/api/tenants/123/members",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert response.status_code == 200
```

---

## Guardrail Fixture Answer Length

> **⚠️ WARNING:** The NEXUS guardrail short-turn bypass fires for queries ≤ 8 words AND answers ≤ 40 words. Test fixture answers must exceed 40 words to avoid the bypass. Always assert on `result.reason` not just `result.passed = True` — the bypass also sets `passed = True`.

```python
# BAD — may hit short-turn bypass
fixture_answer = "The Pro plan costs $99 per month."

# GOOD — exceeds 40-word threshold
fixture_answer = (
    "The Pro plan costs $99 per month and includes access to all core features, "
    "priority support, and up to 10 team members. The Enterprise plan is available "
    "at custom pricing for organizations with advanced requirements."
)
```

---

## Anti-Patterns

| Anti-pattern | Why wrong | Fix |
|---|---|---|
| `unittest.mock.patch` on `db.execute` | Mock/prod divergence — real queries may behave differently | Use real DB with rollback fixture |
| `assert result.passed == True` only | Short-turn bypass also sets `passed = True` | Also assert `result.reason` |
| Hardcoded UUIDs | Collision across test runs | Use `uuid4()` or factory fixtures |
| `time.sleep()` in async tests | Blocks event loop | Use `await asyncio.sleep()` |
| Sharing state between tests | Order-dependent failures | Use `function`-scoped fixtures |

---

## Related Docs

- [Test Structure](test-structure.md)
- [Running Tests](running-tests.md)
- [Guardrails](../14-guardrails/README.md) — short-turn bypass detail
