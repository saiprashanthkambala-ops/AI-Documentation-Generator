"""Server-side Gemini REST adapter with bounded retries and safe errors."""
import asyncio
import logging
import random

import httpx

from backend.config import settings

logger = logging.getLogger(__name__)


class ProviderError(Exception):
    def __init__(self, code: str, message: str, status_code: int | None = None):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _error_message(response: httpx.Response) -> str | None:
    try:
        body = response.json()
    except (ValueError, TypeError):
        return None
    error = body.get("error") if isinstance(body, dict) else None
    message = error.get("message") if isinstance(error, dict) else None
    return message.strip() if isinstance(message, str) and message.strip() else None


async def _backoff(attempt: int) -> None:
    # Google recommends exponential backoff for transient 429/5xx errors.
    delay = min(8.0, 1.0 * (2 ** attempt)) + random.uniform(0.0, 0.5)
    await asyncio.sleep(delay)


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

    model = settings.GEMINI_MODEL.strip()
    if not model:
        raise ProviderError("AI_NOT_CONFIGURED", "GEMINI_MODEL is empty.")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload = {
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

    last_status: int | None = None
    last_detail: str | None = None

    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=settings.GEMINI_API_TIMEOUT) as client:
                response = await client.post(
                    url,
                    headers={
                        "x-goog-api-key": api_key,
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )

            last_status = response.status_code
            last_detail = _error_message(response)

            if response.status_code in (401, 403):
                raise ProviderError(
                    "AI_AUTH_FAILED",
                    "Gemini rejected the API key. Check that the key is active and allowed to use the configured model.",
                    response.status_code,
                )

            if response.status_code == 429:
                if attempt < 2:
                    await _backoff(attempt)
                    continue
                raise ProviderError(
                    "AI_RATE_LIMITED",
                    "Gemini rate limit reached. Please wait briefly and try again.",
                    response.status_code,
                )

            if response.status_code >= 500:
                if attempt < 2:
                    await _backoff(attempt)
                    continue
                detail = (
                    f" Gemini returned: {last_detail}"
                    if last_detail
                    else ""
                )
                raise ProviderError(
                    "AI_PROVIDER_UNAVAILABLE",
                    f"Gemini is temporarily unavailable (HTTP {response.status_code}).{detail}",
                    response.status_code,
                )

            if response.status_code >= 400:
                detail = _error_message(response)
                raise ProviderError(
                    "AI_REQUEST_FAILED",
                    f"Gemini request failed: {detail}"
                    if detail
                    else f"Gemini request failed with HTTP {response.status_code}.",
                    response.status_code,
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
                    response.status_code,
                )

            if not generated_text.strip():
                raise ProviderError(
                    "AI_EMPTY_RESPONSE",
                    "Gemini returned no documentation.",
                    response.status_code,
                )
            return generated_text

        except ProviderError:
            raise
        except httpx.TimeoutException:
            if attempt == 2:
                raise ProviderError(
                    "AI_TIMEOUT",
                    "Gemini took too long to respond.",
                    last_status,
                )
            await _backoff(attempt)
        except httpx.RequestError:
            if attempt == 2:
                raise ProviderError(
                    "AI_PROVIDER_UNAVAILABLE",
                    "Gemini could not be reached. Check your internet connection and try again.",
                    last_status,
                )
            await _backoff(attempt)

    logger.error(
        "Gemini generation exhausted all retries for model %s (status=%s detail=%s)",
        settings.GEMINI_MODEL,
        last_status,
        last_detail,
    )
    raise ProviderError(
        "AI_PROVIDER_UNAVAILABLE",
        "Gemini is temporarily unavailable. Please try again.",
        last_status,
    )


async def status():
    configured = bool(settings.GEMINI_API_KEY.strip())
    return {
        "configured": configured,
        "provider": "Gemini",
        "model": settings.GEMINI_MODEL,
        "message": "Ready" if configured else "Gemini API key is not configured. Add it to secrets/gemini.env.",
    }
