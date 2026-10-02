import io, zipfile, pytest, asyncio
from backend.services.zip_handler import validate_zip
from backend.services.gemini_service import ProviderError

def make_zip(name):
 b=io.BytesIO()
 with zipfile.ZipFile(b,'w') as z:z.writestr(name,'x')
 return b.getvalue()
def test_zip_traversal(tmp_path):
 p=tmp_path/'x.zip'; p.write_bytes(make_zip('../evil.py'))
 assert validate_zip(str(p),p.stat().st_size)[0] is False
def test_zip_absolute(tmp_path):
 p=tmp_path/'x.zip'; p.write_bytes(make_zip('/evil.py'))
 assert validate_zip(str(p),p.stat().st_size)[0] is False
def test_missing_gemini_key(monkeypatch):
 from backend import config
 monkeypatch.setattr(config.settings,'GEMINI_API_KEY','')
 from backend.services.gemini_service import generate
 with pytest.raises(ProviderError) as e: asyncio.run(generate('test'))
 assert e.value.code=='AI_NOT_CONFIGURED'
