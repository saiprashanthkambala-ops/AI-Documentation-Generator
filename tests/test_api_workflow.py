import io, zipfile
from fastapi.testclient import TestClient
from backend.main import app

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
