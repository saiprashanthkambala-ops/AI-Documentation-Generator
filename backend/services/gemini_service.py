"""Server-side Gemini REST adapter with bounded retries and safe errors."""
import asyncio, httpx
from backend.config import settings
class ProviderError(Exception):
    def __init__(self, code, message): self.code=code; self.message=message
async def generate(prompt: str, system: str='') -> str:
    if not settings.GEMINI_API_KEY: raise ProviderError('AI_NOT_CONFIGURED','Gemini is not configured. Add GEMINI_API_KEY to .env.')
    url='https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent'
    payload={'system_instruction':{'parts':[{'text':system}]} ,'contents':[{'parts':[{'text':prompt}]}], 'generationConfig':{'temperature':0.2,'maxOutputTokens':8192}}
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=90) as client:
                r=await client.post(url, params={'key':settings.GEMINI_API_KEY}, json=payload)
            if r.status_code in (401,403): raise ProviderError('AI_AUTH_FAILED','Gemini rejected the API key.')
            if r.status_code==429 and attempt<2: await asyncio.sleep(2**attempt); continue
            if r.status_code>=500 and attempt<2: await asyncio.sleep(2**attempt); continue
            if r.status_code>=400: raise ProviderError('AI_REQUEST_FAILED','Gemini could not process this request.')
            try:
                body=r.json(); candidates=body.get('candidates',[])
                text=''.join(p.get('text','') for c in candidates for p in c.get('content',{}).get('parts',[]))
            except (ValueError, AttributeError, TypeError, KeyError):
                raise ProviderError('AI_MALFORMED_RESPONSE','Gemini returned an unreadable response.')
            if not text.strip(): raise ProviderError('AI_EMPTY_RESPONSE','Gemini returned no documentation.')
            return text
        except httpx.TimeoutException:
            if attempt==2: raise ProviderError('AI_TIMEOUT','Gemini took too long to respond.')
        except httpx.RequestError:
            if attempt==2: raise ProviderError('AI_PROVIDER_UNAVAILABLE','Gemini is temporarily unavailable.')
    raise ProviderError('AI_PROVIDER_UNAVAILABLE','Gemini is temporarily unavailable.')
async def status(): return {'configured':bool(settings.GEMINI_API_KEY), 'provider':'Gemini', 'message':'Ready' if settings.GEMINI_API_KEY else 'Gemini API key is not configured.'}
