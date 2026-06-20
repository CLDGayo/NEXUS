"""Security-header + CORS hardening tests (ZAP 2026-06-20 remediation).

Covers the response-header middleware and tightened CORS allowlist added to
``rag.main`` after the OWASP ZAP scan of https://chat.nexus.gayo-sphere.cloud
flagged:

    * Content Security Policy (CSP) Header Not Set        (Medium)
    * Cross-Domain Misconfiguration (access-control-allow-origin: *)  (Medium)
    * Strict-Transport-Security Header Not Set            (Low)
    * Re-examine Cache-control Directives                 (Info)

These run with no Postgres/Qdrant — they only exercise unauthenticated routes
and the middleware stack.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client() -> TestClient:
    from rag.main import app

    return TestClient(app)


def test_csp_header_present_on_spa(client: TestClient) -> None:
    """The SPA index carries a Content-Security-Policy with frame-ancestors 'self'."""
    response = client.get("/")
    csp = response.headers.get("Content-Security-Policy")
    assert csp is not None, "CSP header missing on SPA root"
    assert "default-src 'self'" in csp
    assert "object-src 'none'" in csp
    assert "frame-ancestors 'self'" in csp


def test_widget_csp_is_embeddable(client: TestClient) -> None:
    """The widget keeps a permissive frame-ancestors so it stays embeddable."""
    response = client.get("/widget")
    csp = response.headers.get("Content-Security-Policy")
    assert csp is not None, "CSP header missing on /widget"
    assert "frame-ancestors *" in csp
    # The non-widget X-Frame-Options must NOT block cross-site framing here.
    assert "X-Frame-Options" not in response.headers


def test_anti_sniffing_and_referrer_headers(client: TestClient) -> None:
    response = client.get("/")
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    assert response.headers.get("X-Frame-Options") == "SAMEORIGIN"


def test_api_responses_are_not_cacheable(client: TestClient) -> None:
    """Sensitive /api/* responses must carry no-store (ZAP cache-control)."""
    # Anonymous hit on a mounted API route — 401 is fine; we only assert headers.
    response = client.post(
        "/api/users/me/password",
        json={"current_password": "x", "new_password": "yyyyyyyy"},
    )
    cache_control = response.headers.get("Cache-Control", "")
    assert "no-store" in cache_control, response.headers


def test_hsts_absent_on_plain_http(client: TestClient) -> None:
    """Plain-http (no scheme, no forwarded proto) must NOT receive HSTS."""
    assert "Strict-Transport-Security" not in client.get("/").headers


def test_hsts_emitted_via_https_scheme(client: TestClient) -> None:
    """A genuine https:// request gets HSTS (covers uvicorn --proxy-headers)."""
    https_client = TestClient(client.app, base_url="https://testserver")
    hsts = https_client.get("/").headers.get("Strict-Transport-Security")
    assert hsts is not None, "HSTS missing on https request"
    assert "max-age=" in hsts
    assert "includeSubDomains" in hsts


def test_hsts_emitted_via_forwarded_proto(client: TestClient) -> None:
    """X-Forwarded-Proto: https triggers HSTS even when uvicorn leaves the
    scheme http (container sees the docker-bridge IP, outside the default
    --forwarded-allow-ips trust list)."""
    resp = client.get("/", headers={"X-Forwarded-Proto": "https"})
    assert "Strict-Transport-Security" in resp.headers


def test_cors_allowlist_excludes_wildcard() -> None:
    """The CORS origin allowlist is explicit — never a bare wildcard."""
    from rag.config import settings

    origins = settings.cors_allow_origins()
    assert origins, "CORS allowlist must not be empty"
    assert "*" not in origins
    assert "https://chat.nexus.gayo-sphere.cloud" in origins


def test_cors_rejects_unknown_origin(client: TestClient) -> None:
    """A disallowed Origin must not be reflected in Access-Control-Allow-Origin."""
    response = client.get("/", headers={"Origin": "https://evil.example.com"})
    acao = response.headers.get("Access-Control-Allow-Origin")
    assert acao != "*"
    assert acao != "https://evil.example.com"


def test_cors_allows_known_origin(client: TestClient) -> None:
    """A whitelisted Origin is reflected back (not wildcarded)."""
    allowed = "https://chat.nexus.gayo-sphere.cloud"
    response = client.get("/", headers={"Origin": allowed})
    assert response.headers.get("Access-Control-Allow-Origin") == allowed
