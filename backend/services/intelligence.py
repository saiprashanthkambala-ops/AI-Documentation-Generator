"""Deterministic manifest, hashing, classification and Python AST evidence."""
import ast, hashlib, json, os
from pathlib import Path
from backend.config import settings
def manifest(root):
    files=[]
    for base,dirs,names in os.walk(root):
        dirs[:]=[d for d in dirs if d not in settings.SKIP_FOLDERS]
        for name in sorted(names):
            p=Path(base)/name; rel=str(p.relative_to(root))
            if p.suffix.lower() not in settings.SOURCE_EXTENSIONS: continue
            data=p.read_bytes(); item={'path':rel,'extension':p.suffix.lower(),'size':len(data),'sha256':hashlib.sha256(data).hexdigest(),'classification':classify(rel)}
            if p.suffix=='.py': item['evidence']=python_evidence(data,rel)
            files.append(item)
    return {'file_count':len(files),'files':files,'languages':sorted({f['extension'] for f in files})}
def classify(path):
    n=path.lower()
    if any(x in n for x in ('test','spec')): return 'test'
    if any(x in n for x in ('route','api','controller','view')): return 'api'
    if any(x in n for x in ('readme','requirement','pyproject','package.json','docker')): return 'configuration'
    return 'source'
def python_evidence(data,path):
    try: tree=ast.parse(data.decode('utf8','replace')); return {'module':ast.get_docstring(tree),'imports':[getattr(x,'name', '') for x in tree.body if isinstance(x,ast.ImportFrom) or isinstance(x,ast.Import)],'symbols':[x.name for x in tree.body if isinstance(x,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef))]}
    except SyntaxError: return {'error':'syntax error'}
def context_for(root, doc_type='README'):
    """Select bounded evidence relevant to the requested documentation type."""
    m=manifest(root); wanted={'API Documentation':{'api','source'},'Setup Guide':{'configuration'},'Configuration Guide':{'configuration'},'Architecture Documentation':{'source','api'},'README':{'source','api','configuration'}}.get(doc_type,{'source','configuration','api'})
    return {'documentation_type':doc_type,'files':[f for f in m['files'] if f['classification'] in wanted],'warnings':[]}
def documentation_plan(root, doc_type='README'):
    c=context_for(root,doc_type); return {'type':doc_type,'sections':['Overview','Evidence and architecture','Setup and usage','Limitations'],'evidence':[f['path'] for f in c['files']],'missing_information':[],'warnings':c['warnings']}
def impact(changes):
    paths=changes['added']+changes['modified']+changes['removed']; affected={'README'}
    for p in paths:
        q=p.lower()
        if any(x in q for x in ('route','api','controller','schema')): affected.add('API Documentation')
        if any(x in q for x in ('config','env','requirement','pyproject','package')): affected.update(('Setup Guide','Configuration Guide'))
        if any(x in q for x in ('database','model','service')): affected.add('Architecture Documentation')
    return {'affected':sorted(affected),'reasons':{d:'Changed evidence may affect this document.' for d in affected}}
def compare(old,new):
    a={x['path']:x for x in old.get('files',[])}; b={x['path']:x for x in new.get('files',[])}
    return {'added':[p for p in b if p not in a],'removed':[p for p in a if p not in b],'modified':[p for p in b if p in a and b[p]['sha256']!=a[p]['sha256']],'unchanged':[p for p in b if p in a and b[p]['sha256']==a[p]['sha256']]}
