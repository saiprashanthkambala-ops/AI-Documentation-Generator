import io, zipfile
from fastapi.testclient import TestClient
from backend.main import app
import backend.services.doc_generator as generator

def archive(files):
 b=io.BytesIO()
 with zipfile.ZipFile(b,'w') as z:
  for path,text in files.items(): z.writestr(path,text)
 b.seek(0); return b

def test_health_and_upload_versions():
 with TestClient(app) as c:
  assert c.get('/api/health').status_code==200
  assert c.get('/api/gemini/status').status_code==200
  r=c.post('/api/upload',data={'name':'api-test'},files={'zip_file':('x.zip',archive({'main.py':'def run(): pass'}),'application/zip')})
  assert r.status_code==200
  pid=r.json()['id']; versions=c.get(f'/api/projects/{pid}/versions').json(); assert len(versions)>=1
  assert c.get(f'/api/projects/{pid}/documentation-versions').status_code==200
  assert c.get(f'/api/projects/{pid}/changes').status_code==200

def test_same_project_reanalysis_creates_change_report():
 with TestClient(app) as c:
  r=c.post('/api/upload',data={'name':'versioned'},files={'zip_file':('x.zip',archive({'main.py':'x=1'}),'application/zip')}); pid=r.json()['id']
  r=c.post(f'/api/projects/{pid}/versions/upload',files={'zip_file':('x.zip',archive({'main.py':'x=2','api.py':'route=True'}),'application/zip')})
  assert r.status_code==200 and r.json()['changes']['modified']==['main.py']
  assert len(c.get(f'/api/projects/{pid}/change-reports').json())>=1

def test_invalid_project_and_type():
 with TestClient(app) as c:
  assert c.get('/api/projects/999999').status_code==404
  assert c.post('/api/projects/999999/generate?doc_type=bad').status_code==404

def test_reject_keeps_document_history():
 with TestClient(app) as c:
  r=c.post('/api/upload',data={'name':'reject-test'},files={'zip_file':('x.zip',archive({'main.py':'x=1'}),'application/zip')}); pid=r.json()['id']
  # no docs means a decision cannot mutate unrelated data
  assert c.post(f'/api/projects/{pid}/documentation/999/decision?decision=reject').status_code==400



def test_generation_progress_endpoint_reports_completed(monkeypatch):
 async def fake_generate(prompt, system="", **kwargs):
  return "# Generated documentation\n\nThis response is based on verified project evidence and contains enough detail for a project README.\n"
 monkeypatch.setattr(generator, "generate", fake_generate)
 with TestClient(app) as c:
  upload = c.post(
   "/api/upload",
   data={"name": "progress-test"},
   files={"zip_file": ("progress.zip", archive({"main.py": "print('ready')"}), "application/zip")},
  )
  assert upload.status_code == 200
  project_id = upload.json()["id"]
  before = c.get(f"/api/projects/{project_id}/generate/progress")
  assert before.status_code == 200
  assert before.json()["status"] == "idle"
  generated = c.post(f"/api/projects/{project_id}/generate")
  assert generated.status_code == 200
  after = c.get(f"/api/projects/{project_id}/generate/progress")
  assert after.status_code == 200
  assert after.json()["status"] == "completed"
  assert after.json()["progress"] == 100
  assert after.json()["elapsed_seconds"] >= 0
  assert "metrics" in after.json()
  assert "source_scan_ms" in after.json()["metrics"]
  assert "total_duration_ms" in after.json()["metrics"]


def test_generation_cancel_endpoint():
    with TestClient(app) as c:
        upload = c.post(
            "/api/upload",
            data={"name": "cancel-test"},
            files={"zip_file": ("cancel.zip", archive({"main.py": "print('cancel')"}), "application/zip")},
        )
        assert upload.status_code == 200
        project_id = upload.json()["id"]

        cancel_resp = c.post(f"/api/projects/{project_id}/generate/cancel")
        assert cancel_resp.status_code == 200
        assert cancel_resp.json()["status"] == "cancelled"
