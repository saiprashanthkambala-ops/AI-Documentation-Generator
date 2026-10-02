import asyncio, httpx, pytest
from backend.services import gemini_service
class FakeClient:
    def __init__(self,*a,**kw): self.calls=0
    async def __aenter__(self): return self
    async def __aexit__(self,*a): pass
    async def post(self,*a,**kw):
        return httpx.Response(200,json={'candidates':[{'content':{'parts':[{'text':'# Verified docs\nEvidence based.'}]}}]})
def test_gemini_success(monkeypatch):
 monkeypatch.setattr(gemini_service.settings,'GEMINI_API_KEY','test-key'); monkeypatch.setattr(gemini_service.httpx,'AsyncClient',FakeClient)
 assert 'Verified' in asyncio.run(gemini_service.generate('evidence'))
def test_gemini_auth_error(monkeypatch):
 class Auth(FakeClient):
  async def post(self,*a,**kw): return httpx.Response(403,json={})
 monkeypatch.setattr(gemini_service.settings,'GEMINI_API_KEY','x'); monkeypatch.setattr(gemini_service.httpx,'AsyncClient',Auth)
 with pytest.raises(gemini_service.ProviderError) as e: asyncio.run(gemini_service.generate('x'))
 assert e.value.code=='AI_AUTH_FAILED'
def test_gemini_retry_then_success(monkeypatch):
 class Retry(FakeClient):
  total=0
  async def post(self,*a,**kw):
   Retry.total+=1
   return httpx.Response(503,json={}) if Retry.total < 2 else httpx.Response(200,json={'candidates':[{'content':{'parts':[{'text':'# Retry success with enough evidence.'}]}}]})
 monkeypatch.setattr(gemini_service.settings,'GEMINI_API_KEY','x'); monkeypatch.setattr(gemini_service.httpx,'AsyncClient',Retry)
 assert 'Retry success' in asyncio.run(gemini_service.generate('x'))
def test_gemini_malformed(monkeypatch):
 class Malformed(FakeClient):
  async def post(self,*a,**kw): return httpx.Response(200,content=b'not-json')
 monkeypatch.setattr(gemini_service.settings,'GEMINI_API_KEY','x'); monkeypatch.setattr(gemini_service.httpx,'AsyncClient',Malformed)
 with pytest.raises(gemini_service.ProviderError) as e: asyncio.run(gemini_service.generate('x'))
 assert e.value.code=='AI_MALFORMED_RESPONSE'
def test_gemini_timeout_exhaustion(monkeypatch):
 class Timeout(FakeClient):
  async def post(self,*a,**kw): raise httpx.TimeoutException('slow')
 monkeypatch.setattr(gemini_service.settings,'GEMINI_API_KEY','x'); monkeypatch.setattr(gemini_service.httpx,'AsyncClient',Timeout)
 with pytest.raises(gemini_service.ProviderError) as e: asyncio.run(gemini_service.generate('x'))
 assert e.value.code=='AI_TIMEOUT'
def test_gemini_empty(monkeypatch):
 class Empty(FakeClient):
  async def post(self,*a,**kw): return httpx.Response(200,json={'candidates':[]})
 monkeypatch.setattr(gemini_service.settings,'GEMINI_API_KEY','x'); monkeypatch.setattr(gemini_service.httpx,'AsyncClient',Empty)
 with pytest.raises(gemini_service.ProviderError) as e: asyncio.run(gemini_service.generate('x'))
 assert e.value.code=='AI_EMPTY_RESPONSE'
