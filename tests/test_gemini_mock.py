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



def test_gemini_connection_error_retries(monkeypatch):
    _fast_retry(monkeypatch)

    class ConnectOnce(FakeClient):
        calls = 0

        async def post(self, *a, **kw):
            ConnectOnce.calls += 1
            if ConnectOnce.calls == 1:
                raise httpx.ConnectError("temporary network failure")
            return httpx.Response(
                200,
                json={"candidates": [{"content": {"parts": [{"text": "# Network retry succeeded."}]}}]},
            )

    monkeypatch.setattr(gemini_service.settings, "GEMINI_API_KEY", "x")
    monkeypatch.setattr(gemini_service.settings, "GEMINI_FALLBACK_MODEL", "")
    monkeypatch.setattr(gemini_service.settings, "GEMINI_MAX_RETRIES", 2)
    monkeypatch.setattr(gemini_service.httpx, "AsyncClient", ConnectOnce)
    assert "Network retry succeeded" in asyncio.run(gemini_service.generate("x"))
    assert ConnectOnce.calls == 2


def test_gemini_rate_limit_error(monkeypatch):
    class RateLimited(FakeClient):
        async def post(self, *a, **kw):
            return httpx.Response(429, json={"error": {"message": "Resource exhausted"}})

    monkeypatch.setattr(gemini_service.settings, "GEMINI_API_KEY", "x")
    monkeypatch.setattr(gemini_service.settings, "GEMINI_FALLBACK_MODEL", "")
    monkeypatch.setattr(gemini_service.httpx, "AsyncClient", RateLimited)
    with pytest.raises(gemini_service.ProviderError) as exc:
        asyncio.run(gemini_service.generate("x"))
    assert exc.value.code == "AI_RATE_LIMITED"
    assert exc.value.status_code == 429


def test_gemini_streaming_sse_success(monkeypatch):
    class FakeStreamResponse:
        status_code = 200
        headers = {}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def aiter_lines(self):
            yield "data: {\"candidates\": [{\"content\": {\"parts\": [{\"text\": \"# Streaming Documentation\\n\"}]}}]}"
            yield ""
            yield "data: {\"candidates\": [{\"content\": {\"parts\": [{\"text\": \"Evidence-backed content from Gemini.\"}]}}]}"
            yield "data: [DONE]"

    class StreamingClient(FakeClient):
        def stream(self, method, url, **kw):
            return FakeStreamResponse()

    received_chunks = []
    def on_chunk(text):
        received_chunks.append(text)

    monkeypatch.setattr(gemini_service.settings, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(gemini_service.httpx, "AsyncClient", StreamingClient)
    text, metrics = asyncio.run(gemini_service.stream_generate("prompt", on_chunk=on_chunk))
    assert "# Streaming Documentation" in text
    assert len(received_chunks) == 2
    assert metrics["chars"] > 20
    assert metrics["ttft_ms"] >= 0


def test_gemini_streaming_cancellation(monkeypatch):
    class HangingStreamResponse:
        status_code = 200
        headers = {}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def aiter_lines(self):
            yield "data: {\"candidates\": [{\"content\": {\"parts\": [{\"text\": \"First chunk\"}]}}]}"
            # Will be cancelled here

    class HangingClient(FakeClient):
        def stream(self, method, url, **kw):
            return HangingStreamResponse()

    cancel_event = asyncio.Event()
    cancel_event.set()

    monkeypatch.setattr(gemini_service.settings, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(gemini_service.httpx, "AsyncClient", HangingClient)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(gemini_service.stream_generate("prompt", cancel_event=cancel_event))

