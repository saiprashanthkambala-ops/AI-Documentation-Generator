import asyncio

import httpx
import pytest

from backend.services import gemini_service


class FakeClient:
    def __init__(self, *a, **kw):
        self.calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        pass

    async def post(self, *a, **kw):
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": "# Verified docs\nEvidence based."}]}}]},
        )


def _fast_retry(monkeypatch):
    async def no_sleep(*args, **kwargs):
        return None

    monkeypatch.setattr(gemini_service, "_backoff", no_sleep)


def test_gemini_success(monkeypatch):
    monkeypatch.setattr(gemini_service.settings, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(gemini_service.httpx, "AsyncClient", FakeClient)
    assert "Verified" in asyncio.run(gemini_service.generate("evidence"))


def test_gemini_auth_error(monkeypatch):
    class Auth(FakeClient):
        async def post(self, *a, **kw):
            return httpx.Response(403, json={})

    monkeypatch.setattr(gemini_service.settings, "GEMINI_API_KEY", "x")
    monkeypatch.setattr(gemini_service.httpx, "AsyncClient", Auth)
    with pytest.raises(gemini_service.ProviderError) as exc:
        asyncio.run(gemini_service.generate("x"))
    assert exc.value.code == "AI_AUTH_FAILED"
    assert exc.value.status_code == 403


def test_gemini_retry_then_success(monkeypatch):
    _fast_retry(monkeypatch)

    class Retry(FakeClient):
        total = 0

        async def post(self, *a, **kw):
            Retry.total += 1
            return (
                httpx.Response(503, json={"error": {"message": "capacity"}})
                if Retry.total < 2
                else httpx.Response(
                    200,
                    json={
                        "candidates": [
                            {"content": {"parts": [{"text": "# Retry success with enough evidence."}]}}
                        ]
                    },
                )
            )

    monkeypatch.setattr(gemini_service.settings, "GEMINI_API_KEY", "x")
    monkeypatch.setattr(gemini_service.httpx, "AsyncClient", Retry)
    assert "Retry success" in asyncio.run(gemini_service.generate("x"))


def test_gemini_fallback_model(monkeypatch):
    _fast_retry(monkeypatch)

    class PrimaryDown(FakeClient):
        async def post(self, url, **kw):
            if "gemini-3.8-flash" in url:
                return httpx.Response(503, json={"error": {"message": "no capacity"}})
            return httpx.Response(
                200,
                json={"candidates": [{"content": {"parts": [{"text": "# Fallback success with evidence."}]}}]},
            )

    monkeypatch.setattr(gemini_service.settings, "GEMINI_API_KEY", "x")
    monkeypatch.setattr(gemini_service.settings, "GEMINI_MAX_RETRIES", 1)
    monkeypatch.setattr(gemini_service.settings, "GEMINI_MODEL", "gemini-3.8-flash")
    monkeypatch.setattr(gemini_service.settings, "GEMINI_FALLBACK_MODEL", "gemini-3.5-flash-lite")
    monkeypatch.setattr(gemini_service.httpx, "AsyncClient", PrimaryDown)
    assert "Fallback success" in asyncio.run(gemini_service.generate("x"))


def test_gemini_malformed(monkeypatch):
    class Malformed(FakeClient):
        async def post(self, *a, **kw):
            return httpx.Response(200, content=b"not-json")

    monkeypatch.setattr(gemini_service.settings, "GEMINI_API_KEY", "x")
    monkeypatch.setattr(gemini_service.httpx, "AsyncClient", Malformed)
    with pytest.raises(gemini_service.ProviderError) as exc:
        asyncio.run(gemini_service.generate("x"))
    assert exc.value.code == "AI_MALFORMED_RESPONSE"


def test_gemini_timeout_exhaustion(monkeypatch):
    _fast_retry(monkeypatch)

    class Timeout(FakeClient):
        async def post(self, *a, **kw):
            raise httpx.TimeoutException("slow")

    monkeypatch.setattr(gemini_service.settings, "GEMINI_API_KEY", "x")
    monkeypatch.setattr(gemini_service.settings, "GEMINI_FALLBACK_MODEL", "")
    monkeypatch.setattr(gemini_service.httpx, "AsyncClient", Timeout)
    with pytest.raises(gemini_service.ProviderError) as exc:
        asyncio.run(gemini_service.generate("x"))
    assert exc.value.code == "AI_PROVIDER_UNAVAILABLE"


def test_gemini_empty(monkeypatch):
    class Empty(FakeClient):
        async def post(self, *a, **kw):
            return httpx.Response(200, json={"candidates": []})

    monkeypatch.setattr(gemini_service.settings, "GEMINI_API_KEY", "x")
    monkeypatch.setattr(gemini_service.httpx, "AsyncClient", Empty)
    with pytest.raises(gemini_service.ProviderError) as exc:
        asyncio.run(gemini_service.generate("x"))
    assert exc.value.code == "AI_EMPTY_RESPONSE"
