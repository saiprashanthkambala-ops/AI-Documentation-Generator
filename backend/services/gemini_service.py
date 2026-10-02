"""Server-side Gemini REST adapter with fast retries and model fallback."""

from __future__ import annotations

import asyncio
import logging
import random
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from backend.config import settings

logger = logging.getLogger(__name__)

TRANSIENT_STATUS_CODES = {408, 429, 500, 502, 503, 504}


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

    # Keep retries short for interactive generation while using exponential
    # backoff + jitter as recommended for transient Gemini errors.
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


async def _generate_with_model(
    client: httpx.AsyncClient,
    model: str,
    prompt: str,
    system: str,
    thinking_level: str | None,
    max_output_tokens: int | None,
) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
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
    if system:
        payload["system_instruction"] = {"parts": [{"text": system}]}

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
        raise ProviderError(
            "AI_TRANSIENT_ERROR",
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


async def generate(
    prompt: str,
    system: str = "",
    *,
    thinking_level: str | None = None,
    max_output_tokens: int | None = None,
) -> str:
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

    async with httpx.AsyncClient(timeout=settings.GEMINI_API_TIMEOUT) as client:
        for model_index, model in enumerate(models):
            attempts = max(1, int(settings.GEMINI_MAX_RETRIES))
            for attempt in range(attempts):
                try:
                    result = await _generate_with_model(
                        client,
                        model,
                        prompt,
                        system,
                        thinking_level,
                        max_output_tokens,
                    )
                    if model_index > 0:
                        logger.warning(
                            "Gemini primary model %s was unavailable; fallback %s succeeded.",
                            models[0],
                            model,
                        )
                    return result
                except ProviderError as exc:
                    last_error = exc
                    if exc.code != "AI_TRANSIENT_ERROR":
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
        raise ProviderError(
            "AI_PROVIDER_UNAVAILABLE",
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
