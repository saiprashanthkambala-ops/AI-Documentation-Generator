import io, zipfile
from fastapi.testclient import TestClient
from backend.main import app
import backend.services.doc_generator as generator

def archive(files):
 b=io.BytesIO()
 with zipfile.ZipFile(b,'w') as z:
  for path,text in files.items(): z.writestr(path,text)
 b.seek(0); return b
async def fake_generate(prompt,system=''):
 return '# Evidence-backed documentation\n\nThis proposal is based only on supplied project evidence and is sufficiently detailed for validation.\n\n## Setup\nVerified from source evidence.'
def test_complete_mocked_maintenance_approve_and_reject(monkeypatch):
 monkeypatch.setattr(generator,'generate',fake_generate)
 with TestClient(app) as c:
  first=c.post('/api/upload',data={'name':'e2e'},files={'zip_file':('x.zip',archive({'main.py':'x=1','old.py':'old'}),'application/zip')}); assert first.status_code==200
  pid=first.json()['id']; assert len(c.get(f'/api/projects/{pid}/versions').json())==1
  generated=c.post(f'/api/projects/{pid}/generate?doc_type=README'); assert generated.status_code==200
  docs=c.get(f'/api/projects/{pid}/documentation-versions').json(); assert len(docs)==1 and docs[0]['status']=='CURRENT'
  second=c.post(f'/api/projects/{pid}/versions/upload',files={'zip_file':('x.zip',archive({'main.py':'x=2','new.py':'new'}),'application/zip')}); assert second.status_code==200
  change=second.json(); assert 'main.py' in change['changes']['modified']; assert 'new.py' in change['changes']['added']; assert 'old.py' in change['changes']['removed']
  docs=c.get(f'/api/projects/{pid}/documentation-versions').json(); assert docs[0]['status']=='OUTDATED'
  proposal=c.post(f'/api/projects/{pid}/maintenance'); assert proposal.status_code==200
  proposal_id=proposal.json()['documentation_version_id']; assert proposal.json()['status']=='DRAFT'
  diff=c.get(f'/api/projects/{pid}/documentation-diff/{proposal_id}'); assert diff.status_code==200
  approved=c.post(f'/api/projects/{pid}/documentation/{proposal_id}/decision?decision=approve'); assert approved.json()['status']=='CURRENT'
  docs=c.get(f'/api/projects/{pid}/documentation-versions').json(); assert len(docs)>=2 and any(d['status']=='SUPERSEDED' for d in docs)
  current=next(d['content'] for d in docs if d['status']=='CURRENT')
  rejected=c.post(f'/api/projects/{pid}/maintenance'); assert rejected.status_code==200
  rejected_id=rejected.json()['documentation_version_id']; assert c.post(f'/api/projects/{pid}/documentation/{rejected_id}/decision?decision=reject').json()['status']=='REJECTED'
  docs=c.get(f'/api/projects/{pid}/documentation-versions').json(); assert any(d['id']==rejected_id and d['status']=='REJECTED' for d in docs)
  assert next(d['content'] for d in docs if d['status']=='CURRENT')==current
