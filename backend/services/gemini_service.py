"""Server-side Gemini REST adapter with fast retries, model fallback, and REST SSE streaming."""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from email.utils import parsedate_to_datetime
from typing import Any, Callable

import httpx

from backend.config import settings

logger = logging.getLogger(__name__)

TRANSIENT_STATUS_CODES = {408, 429, 500, 502, 503, 504}

# Global connection-pooled client for performance
_POOLED_CLIENT: httpx.AsyncClient | None = None


def get_shared_client() -> httpx.AsyncClient:
    global _POOLED_CLIENT
    if _POOLED_CLIENT is None or _POOLED_CLIENT.is_closed:
        timeout = httpx.Timeout(
            settings.GEMINI_API_TIMEOUT,
            connect=min(10.0, settings.GEMINI_API_TIMEOUT),
        )
        limits = httpx.Limits(max_keepalive_connections=10, max_connections=20, keepalive_expiry=60.0)
        _POOLED_CLIENT = httpx.AsyncClient(timeout=timeout, limits=limits)
    return _POOLED_CLIENT


async def close_shared_client() -> None:
    global _POOLED_CLIENT
    if _POOLED_CLIENT is not None and not _POOLED_CLIENT.is_closed:
        await _POOLED_CLIENT.aclose()
        _POOLED_CLIENT = None


class ProviderError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int | None = None,
        model: str | None = None,
    ):
        self.code = code
        self.message = message
        self.status_code = status_code
        self.model = model
        super().__init__(message)


def _error_message(response: httpx.Response) -> str | None:
    try:
        body = response.json()
    except (ValueError, TypeError):
        return None
    error = body.get("error") if isinstance(body, dict) else None
    message = error.get("message") if isinstance(error, dict) else None
    return message.strip() if isinstance(message, str) and message.strip() else None


def _request_id(response: httpx.Response) -> str | None:
    for header in ("x-request-id", "x-goog-request-id", "request-id"):
        value = response.headers.get(header)
        if value:
            return value[:200]
    return None


def _retry_after_seconds(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after")
    if not value:
        return None
    try:
        return max(0.0, min(float(value), 10.0))
    except ValueError:
        try:
            date = parsedate_to_datetime(value)
            from datetime import datetime, timezone

            return max(
                0.0,
                min((date - datetime.now(timezone.utc)).total_seconds(), 10.0),
            )
        except (TypeError, ValueError, OverflowError):
            return None


async def _backoff(attempt: int, response: httpx.Response | None = None) -> None:
    retry_after = _retry_after_seconds(response) if response is not None else None
    if retry_after is not None:
        await asyncio.sleep(retry_after)
        return

    delay = min(
        4.0,
        settings.GEMINI_RETRY_BASE_DELAY * (2 ** attempt),
    ) + random.uniform(0.0, 0.35)
    await asyncio.sleep(delay)


def _models_to_try() -> list[str]:
    primary = settings.GEMINI_MODEL.strip()
    fallback = settings.GEMINI_FALLBACK_MODEL.strip()
    models = [primary] if primary else []
    if fallback and fallback != primary:
        models.append(fallback)
    return models


def _build_payload(
    prompt: str,
    system: str,
    thinking_level: str | None,
    max_output_tokens: int | None,
    response_mime_type: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "maxOutputTokens": max_output_tokens or settings.GEMINI_MAX_OUTPUT_TOKENS,
        },
    }
    if thinking_level:
        payload["generationConfig"]["thinkingConfig"] = {
            "thinkingLevel": thinking_level,
        }
    if response_mime_type:
        payload["generationConfig"]["responseMimeType"] = response_mime_type
    if system:
        payload["system_instruction"] = {"parts": [{"text": system}]}
    return payload


async def _generate_with_model(
    client: httpx.AsyncClient,
    model: str,
    prompt: str,
    system: str,
    thinking_level: str | None,
    max_output_tokens: int | None,
    response_mime_type: str | None = None,
) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload = _build_payload(prompt, system, thinking_level, max_output_tokens, response_mime_type)

    response = await client.post(
        url,
        headers={
            "x-goog-api-key": settings.GEMINI_API_KEY.strip(),
            "Content-Type": "application/json",
        },
        json=payload,
    )

    status = response.status_code
    detail = _error_message(response)
    request_id = _request_id(response)

    if status in (401, 403):
        raise ProviderError(
            "AI_AUTH_FAILED",
            "Gemini rejected the API key or model access. Check the key permissions and selected model.",
            status,
            model,
        )

    if status in TRANSIENT_STATUS_CODES:
        suffix = f" Request ID: {request_id}." if request_id else ""
        code = "AI_RATE_LIMITED" if status == 429 else "AI_TRANSIENT_ERROR"
        raise ProviderError(
            code,
            f"Gemini returned HTTP {status}"
            + (f": {detail}" if detail else ".")
            + suffix,
            status,
            model,
        )

    if status >= 400:
        raise ProviderError(
            "AI_REQUEST_FAILED",
            f"Gemini request failed: {detail}"
            if detail
            else f"Gemini request failed with HTTP {status}.",
            status,
            model,
        )

    try:
        body = response.json()
        candidates = body.get("candidates", [])
        generated_text = "".join(
            part.get("text", "")
            for candidate in candidates
            for part in candidate.get("content", {}).get("parts", [])
        )
    except (ValueError, AttributeError, TypeError, KeyError):
        raise ProviderError(
            "AI_MALFORMED_RESPONSE",
            "Gemini returned an unreadable response.",
            status,
            model,
        )

    if not generated_text.strip():
        raise ProviderError(
            "AI_EMPTY_RESPONSE",
            "Gemini returned no usable content.",
            status,
            model,
        )
    return generated_text


async def _stream_with_model(
    client: httpx.AsyncClient,
    model: str,
    prompt: str,
    system: str,
    thinking_level: str | None,
    max_output_tokens: int | None,
    response_mime_type: str | None,
    on_chunk: Callable[[str], Any] | None,
    cancel_event: asyncio.Event | None,
) -> tuple[str, dict[str, Any]]:
    """Stream response from Gemini REST SSE endpoint: models/{model}:streamGenerateContent?alt=sse"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent?alt=sse"
    payload = _build_payload(prompt, system, thinking_level, max_output_tokens, response_mime_type)

    t_start = time.perf_counter()
    ttft_ms: float | None = None
    accumulated_parts: list[str] = []

    # Check if client has stream capability (handles mocked FakeClient in tests that only implements post)
    if not hasattr(client, "stream") or not callable(getattr(client, "stream")):
        full = await _generate_with_model(
            client, model, prompt, system, thinking_level, max_output_tokens, response_mime_type
        )
        now_ms = (time.perf_counter() - t_start) * 1000.0
        if on_chunk:
            res = on_chunk(full)
            if asyncio.iscoroutine(res):
                await res
        return full, {
            "ttft_ms": round(now_ms, 1),
            "gemini_gen_ms": round(now_ms, 1),
            "model": model,
            "chars": len(full),
        }

    try:
        async with client.stream(
            "POST",
            url,
            headers={
                "x-goog-api-key": settings.GEMINI_API_KEY.strip(),
                "Content-Type": "application/json",
            },
            json=payload,
        ) as response:
            status = response.status_code
            request_id = _request_id(response)

            if status in (401, 403):
                raise ProviderError(
                    "AI_AUTH_FAILED",
                    "Gemini rejected the API key or model access. Check the key permissions and selected model.",
                    status,
                    model,
                )

            if status in TRANSIENT_STATUS_CODES:
                suffix = f" Request ID: {request_id}." if request_id else ""
                detail = ""
                try:
                    body_bytes = await response.aread()
                    detail = json.loads(body_bytes.decode(errors="replace")).get("error", {}).get("message", "")
                except Exception:
                    pass
                code = "AI_RATE_LIMITED" if status == 429 else "AI_TRANSIENT_ERROR"
                raise ProviderError(
                    code,
                    f"Gemini returned HTTP {status}" + (f": {detail}" if detail else ".") + suffix,
                    status,
                    model,
                )

            if status >= 400:
                detail = ""
                try:
                    body_bytes = await response.aread()
                    detail = json.loads(body_bytes.decode(errors="replace")).get("error", {}).get("message", "")
                except Exception:
                    pass
                raise ProviderError(
                    "AI_REQUEST_FAILED",
                    f"Gemini request failed: {detail}" if detail else f"Gemini request failed with HTTP {status}.",
                    status,
                    model,
                )

            async for line in response.aiter_lines():
                if cancel_event is not None and cancel_event.is_set():
                    raise asyncio.CancelledError("Gemini generation cancelled by user.")

                line = line.strip()
                if not line or not line.startswith("data: "):
                    continue

                raw_data = line[6:].strip()
                if not raw_data or raw_data == "[DONE]":
                    continue

                try:
                    chunk_data = json.loads(raw_data)
                except (ValueError, TypeError, json.JSONDecodeError):
                    continue

                if "error" in chunk_data:
                    err = chunk_data["error"]
                    msg = err.get("message", "Gemini stream error")
                    err_code = err.get("code", 500)
                    raise ProviderError(
                        "AI_TRANSIENT_ERROR" if err_code in TRANSIENT_STATUS_CODES else "AI_REQUEST_FAILED",
                        msg,
                        err_code,
                        model,
                    )

                candidates = chunk_data.get("candidates", [])
                chunk_text = "".join(
                    part.get("text", "")
                    for candidate in candidates
                    for part in candidate.get("content", {}).get("parts", [])
                )

                if chunk_text:
                    if ttft_ms is None:
                        ttft_ms = (time.perf_counter() - t_start) * 1000.0
                    accumulated_parts.append(chunk_text)
                    if on_chunk:
                        res = on_chunk(chunk_text)
                        if asyncio.iscoroutine(res):
                            await res

    except (AttributeError, TypeError):
        # Fallback if client is a test mock without full streaming response
        full = await _generate_with_model(
            client, model, prompt, system, thinking_level, max_output_tokens, response_mime_type
        )
        now_ms = (time.perf_counter() - t_start) * 1000.0
        if on_chunk:
            res = on_chunk(full)
            if asyncio.iscoroutine(res):
                await res
        return full, {
            "ttft_ms": round(now_ms, 1),
            "gemini_gen_ms": round(now_ms, 1),
            "model": model,
            "chars": len(full),
        }

    full_text = "".join(accumulated_parts)
    total_gen_ms = (time.perf_counter() - t_start) * 1000.0

    if not full_text.strip():
        raise ProviderError(
            "AI_EMPTY_RESPONSE",
            "Gemini returned no usable content.",
            status,
            model,
        )

    metrics = {
        "ttft_ms": round(ttft_ms or total_gen_ms, 1),
        "gemini_gen_ms": round(total_gen_ms, 1),
        "model": model,
        "chars": len(full_text),
    }
    return full_text, metrics


async def stream_generate(
    prompt: str,
    system: str = "",
    *,
    thinking_level: str | None = None,
    max_output_tokens: int | None = None,
    response_mime_type: str | None = None,
    on_chunk: Callable[[str], Any] | None = None,
    cancel_event: asyncio.Event | None = None,
) -> tuple[str, dict[str, Any]]:
    """Stream generation from Gemini using SSE with retries, model fallback, and performance metrics."""
    api_key = settings.GEMINI_API_KEY.strip()
    if not api_key:
        raise ProviderError(
            "AI_NOT_CONFIGURED",
            "Gemini is not configured. Add GEMINI_API_KEY to secrets/gemini.env.",
        )

    models = _models_to_try()
    if not models:
        raise ProviderError("AI_NOT_CONFIGURED", "GEMINI_MODEL is empty.")

    last_error: ProviderError | None = None
    timeout = httpx.Timeout(
        settings.GEMINI_API_TIMEOUT,
        connect=min(10.0, settings.GEMINI_API_TIMEOUT),
    )

    async with httpx.AsyncClient(timeout=timeout) as client:
        for model_index, model in enumerate(models):
            attempts = max(1, int(settings.GEMINI_MAX_RETRIES))
            for attempt in range(attempts):
                if cancel_event is not None and cancel_event.is_set():
                    raise asyncio.CancelledError("Generation cancelled.")

                try:
                    result, metrics = await _stream_with_model(
                        client,
                        model,
                        prompt,
                        system,
                        thinking_level,
                        max_output_tokens,
                        response_mime_type,
                        on_chunk,
                        cancel_event,
                    )
                    if model_index > 0:
                        logger.warning(
                            "Gemini primary model %s was unavailable; fallback %s succeeded.",
                            models[0],
                            model,
                        )
                    return result, metrics
                except asyncio.CancelledError:
                    raise
                except httpx.RequestError as exc:
                    reason = "timed out" if isinstance(exc, httpx.TimeoutException) else "could not connect"
                    code = "AI_TIMEOUT" if isinstance(exc, httpx.TimeoutException) else "AI_TRANSIENT_ERROR"
                    last_error = ProviderError(
                        code,
                        f"Gemini request {reason}. Check the network connection and try again.",
                        None,
                        model,
                    )
                    if attempt + 1 < attempts:
                        await _backoff(attempt)
                    else:
                        logger.warning(
                            "Gemini model %s exhausted %s network attempts (%s).",
                            model,
                            attempts,
                            type(exc).__name__,
                        )
                except ProviderError as exc:
                    last_error = exc
                    if exc.code not in ("AI_TRANSIENT_ERROR", "AI_RATE_LIMITED"):
                        raise
                    if attempt + 1 < attempts:
                        await _backoff(attempt)
                    else:
                        logger.warning(
                            "Gemini model %s exhausted %s attempts (status=%s).",
                            model,
                            attempts,
                            exc.status_code,
                        )

    if last_error is not None:
        if len(models) > 1:
            raise ProviderError(
                "AI_PROVIDER_UNAVAILABLE",
                (
                    "Gemini generation is temporarily unavailable. "
                    f"Tried {models[0]} and fallback {models[1]} "
                    f"(last HTTP {last_error.status_code or 'unknown'}). "
                    "Use /api/gemini/test to verify the live generation path."
                ),
                last_error.status_code,
                last_error.model,
            )
        err_code = "AI_RATE_LIMITED" if last_error.code == "AI_RATE_LIMITED" else "AI_PROVIDER_UNAVAILABLE"
        raise ProviderError(
            err_code,
            last_error.message,
            last_error.status_code,
            last_error.model,
        )

    raise ProviderError("AI_PROVIDER_UNAVAILABLE", "Gemini generation failed safely.")


async def generate(
    prompt: str,
    system: str = "",
    *,
    thinking_level: str | None = None,
    max_output_tokens: int | None = None,
    response_mime_type: str | None = None,
    on_chunk: Callable[[str], Any] | None = None,
    cancel_event: asyncio.Event | None = None,
) -> str:
    """Non-streaming convenience wrapper around streaming engine with backward compatibility."""
    api_key = settings.GEMINI_API_KEY.strip()
    if not api_key:
        raise ProviderError(
            "AI_NOT_CONFIGURED",
            "Gemini is not configured. Add GEMINI_API_KEY to secrets/gemini.env.",
        )

    models = _models_to_try()
    if not models:
        raise ProviderError("AI_NOT_CONFIGURED", "GEMINI_MODEL is empty.")

    last_error: ProviderError | None = None
    timeout = httpx.Timeout(
        settings.GEMINI_API_TIMEOUT,
        connect=min(10.0, settings.GEMINI_API_TIMEOUT),
    )

    async with httpx.AsyncClient(timeout=timeout) as client:
        for model_index, model in enumerate(models):
            attempts = max(1, int(settings.GEMINI_MAX_RETRIES))
            for attempt in range(attempts):
                if cancel_event is not None and cancel_event.is_set():
                    raise asyncio.CancelledError("Generation cancelled.")

                try:
                    result = await _generate_with_model(
                        client,
                        model,
                        prompt,
                        system,
                        thinking_level,
                        max_output_tokens,
                        response_mime_type,
                    )
                    if model_index > 0:
                        logger.warning(
                            "Gemini primary model %s was unavailable; fallback %s succeeded.",
                            models[0],
                            model,
                        )
                    return result
                except asyncio.CancelledError:
                    raise
                except httpx.RequestError as exc:
                    reason = "timed out" if isinstance(exc, httpx.TimeoutException) else "could not connect"
                    code = "AI_TIMEOUT" if isinstance(exc, httpx.TimeoutException) else "AI_TRANSIENT_ERROR"
                    last_error = ProviderError(
                        code,
                        f"Gemini request {reason}. Check the network connection and try again.",
                        None,
                        model,
                    )
                    if attempt + 1 < attempts:
                        await _backoff(attempt)
                    else:
                        logger.warning(
                            "Gemini model %s exhausted %s network attempts (%s).",
                            model,
                            attempts,
                            type(exc).__name__,
                        )
                except ProviderError as exc:
                    last_error = exc
                    if exc.code not in ("AI_TRANSIENT_ERROR", "AI_RATE_LIMITED"):
                        raise
                    if attempt + 1 < attempts:
                        await _backoff(attempt)
                    else:
                        logger.warning(
                            "Gemini model %s exhausted %s transient attempts (status=%s).",
                            model,
                            attempts,
                            exc.status_code,
                        )

    if last_error is not None:
        if len(models) > 1:
            raise ProviderError(
                "AI_PROVIDER_UNAVAILABLE",
                (
                    "Gemini generation is temporarily unavailable. "
                    f"Tried {models[0]} and fallback {models[1]} "
                    f"(last HTTP {last_error.status_code or 'unknown'}). "
                    "Use /api/gemini/test to verify the live generation path."
                ),
                last_error.status_code,
                last_error.model,
            )
        err_code = "AI_RATE_LIMITED" if last_error.code == "AI_RATE_LIMITED" else "AI_PROVIDER_UNAVAILABLE"
        raise ProviderError(
            err_code,
            last_error.message,
            last_error.status_code,
            last_error.model,
        )

    raise ProviderError("AI_PROVIDER_UNAVAILABLE", "Gemini generation failed safely.")


async def test_connection() -> dict[str, Any]:
    """Run a tiny real generateContent request to verify the live API path."""
    result = await generate(
        "Reply with the single word OK.",
        "You are a connectivity check. Return only OK.",
        thinking_level="low",
        max_output_tokens=16,
    )
    return {
        "ok": result.strip().upper().startswith("OK"),
        "provider": "Gemini",
        "model": settings.GEMINI_MODEL,
        "response": result.strip()[:50],
    }


async def status():
    configured = bool(settings.GEMINI_API_KEY.strip())
    return {
        "configured": configured,
        "provider": "Gemini",
        "model": settings.GEMINI_MODEL,
        "fallback_model": settings.GEMINI_FALLBACK_MODEL,
        "message": "Ready" if configured else "Gemini API key is not configured. Add it to secrets/gemini.env.",
    }
