import json
from backend.services.intelligence import manifest,compare,impact,documentation_plan
def test_manifest_and_hash(tmp_path):
 (tmp_path/'main.py').write_text('import os\ndef run(): pass')
 m=manifest(tmp_path); assert m['file_count']==1 and len(m['files'][0]['sha256'])==64
def test_compare_and_impact():
 old={'files':[{'path':'api/routes.py','sha256':'a'}]}; new={'files':[{'path':'api/routes.py','sha256':'b'},{'path':'config.yml','sha256':'c'}]}
 c=compare(old,new); assert c['modified']==['api/routes.py']; assert 'API Documentation' in impact(c)['affected']
def test_plan(tmp_path):
 (tmp_path/'README.md').write_text('hello'); assert documentation_plan(tmp_path)['type']=='README'
