"""Server-side Gemini REST adapter with bounded retries and safe errors."""
import asyncio
import logging

import httpx

from backend.config import settings

logger = logging.getLogger(__name__)


class ProviderError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _error_message(response: httpx.Response) -> str | None:
    try:
        body = response.json()
    except (ValueError, TypeError):
        return None
    error = body.get("error") if isinstance(body, dict) else None
    message = error.get("message") if isinstance(error, dict) else None
    return message.strip() if isinstance(message, str) and message.strip() else None


async def generate(prompt: str, system: str = "") -> str:
    api_key = settings.GEMINI_API_KEY.strip()
    if not api_key:
        raise ProviderError("AI_NOT_CONFIGURED",
                             "Gemini is not configured. Add GEMINI_API_KEY to secrets/gemini.env.")

    model = settings.GEMINI_MODEL.strip()
    if not model:
        raise ProviderError("AI_NOT_CONFIGURED", "GEMINI_MODEL is empty.")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "maxOutputTokens": settings.GEMINI_MAX_OUTPUT_TOKENS,
        },
    }
    if system:
        payload["system_instruction"] = {"parts": [{"text": system}]}

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

            if response.status_code in (401, 403):
                raise ProviderError(
                    "AI_AUTH_FAILED",
                    "Gemini rejected the API key. Check that the key is active and allowed to use the configured model.",
                )

            if response.status_code == 429:
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise ProviderError("AI_RATE_LIMITED",
                                    "Gemini rate limit reached. Try again after a short delay.")

            if response.status_code >= 500:
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise ProviderError("AI_PROVIDER_UNAVAILABLE",
                                    "Gemini is temporarily unavailable. Please try again.")

            if response.status_code >= 400:
                detail = _error_message(response)
                raise ProviderError(
                    "AI_REQUEST_FAILED",
                    f"Gemini request failed: {detail}" if detail else "Gemini could not process this request.",
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
                raise ProviderError("AI_MALFORMED_RESPONSE",
                                    "Gemini returned an unreadable response.")

            if not generated_text.strip():
                raise ProviderError("AI_EMPTY_RESPONSE", "Gemini returned no documentation.")
            return generated_text

        except ProviderError:
            raise
        except httpx.TimeoutException:
            if attempt == 2:
                raise ProviderError("AI_TIMEOUT", "Gemini took too long to respond.")
            await asyncio.sleep(2 ** attempt)
        except httpx.RequestError:
            if attempt == 2:
                raise ProviderError(
                    "AI_PROVIDER_UNAVAILABLE",
                    "Gemini could not be reached. Check your internet connection and try again.",
                )
            await asyncio.sleep(2 ** attempt)

    logger.error("Gemini generation exhausted all retries for model %s", settings.GEMINI_MODEL)
    raise ProviderError("AI_PROVIDER_UNAVAILABLE", "Gemini is temporarily unavailable.")


async def status():
    configured = bool(settings.GEMINI_API_KEY.strip())
    return {
        "configured": configured,
        "provider": "Gemini",
        "model": settings.GEMINI_MODEL,
        "message": "Ready" if configured else "Gemini API key is not configured. Add it to secrets/gemini.env.",
    }
