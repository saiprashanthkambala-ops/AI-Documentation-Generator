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


def test_zip_upload_limit_is_200_mb():
    from backend.config import settings
    from backend.services.zip_handler import validate_zip

    limit = settings.MAX_ZIP_SIZE_MB * 1024 * 1024
    assert settings.MAX_ZIP_SIZE_MB == 200
    assert validate_zip("missing.zip", limit)[1] == "Invalid ZIP archive"
    assert validate_zip("missing.zip", limit + 1)[1] == "ZIP exceeds 200MB limit"


def test_50mb_zip_passes_validation(tmp_path):
    from backend.services.zip_handler import validate_zip

    # Build a valid 50 MB ZIP archive containing a small python file + 50 MB uncompressed payload
    zip_file = tmp_path / "test_50mb.zip"
    payload_50mb = b"0" * (50 * 1024 * 1024)
    with zipfile.ZipFile(zip_file, "w", compression=zipfile.ZIP_STORED) as z:
        z.writestr("main.py", "print('hello from 50mb test')\n")
        z.writestr("data.txt", payload_50mb)

    file_size = zip_file.stat().st_size
    assert file_size >= 50 * 1024 * 1024
    valid, err = validate_zip(str(zip_file), file_size)
    assert valid is True
    assert err == ""


def test_200mb_boundary_and_exceed_rejection(tmp_path):
    from backend.config import settings
    from backend.services.zip_handler import validate_zip
    from fastapi.testclient import TestClient
    from backend.main import app

    limit_bytes = settings.MAX_ZIP_SIZE_MB * 1024 * 1024
    assert limit_bytes == 200 * 1024 * 1024

    # Create a small valid zip
    valid_zip = tmp_path / "valid.zip"
    with zipfile.ZipFile(valid_zip, "w") as z:
        z.writestr("app.py", "x = 1\n")

    # Boundary test: exactly 200 MB
    valid_boundary, err_boundary = validate_zip(str(valid_zip), limit_bytes)
    assert valid_boundary is True
    assert err_boundary == ""

    # Over limit test: 200 MB + 1 byte
    valid_over, err_over = validate_zip(str(valid_zip), limit_bytes + 1)
    assert valid_over is False
    assert err_over == "ZIP exceeds 200MB limit"

    # API test: client upload exceeding 200 MB is rejected with 400
    client = TestClient(app)
    # Send a tiny zip with reported length exceeding 200 MB
    oversized_bytes = b"PK\x05\x06" + b"\x00" * 18 + b"X" * (limit_bytes + 1 - 22)
    resp = client.post(
        "/api/upload",
        data={"name": "oversized-project"},
        files={"zip_file": ("oversized.zip", oversized_bytes, "application/zip")},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "ZIP exceeds 200MB limit"


def test_frontend_and_backend_limits_match():
    import re
    from pathlib import Path
    from backend.config import settings

    root = Path(__file__).resolve().parents[1]
    upload_js = (root / "frontend" / "js" / "upload.js").read_text(encoding="utf-8")
    upload_html = (root / "frontend" / "upload.html").read_text(encoding="utf-8")

    # Frontend upload.js constant
    match = re.search(r"const\s+MAX_ZIP_SIZE_BYTES\s*=\s*([^;]+);", upload_js)
    assert match is not None
    frontend_limit = eval(match.group(1))
    backend_limit = settings.MAX_ZIP_SIZE_MB * 1024 * 1024

    assert frontend_limit == 200 * 1024 * 1024
    assert frontend_limit == backend_limit

    # Frontend HTML text
    assert "max 200MB" in upload_html
    assert "max 20MB" not in upload_html

