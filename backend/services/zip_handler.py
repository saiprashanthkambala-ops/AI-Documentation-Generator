import zipfile
from pathlib import Path
from backend.config import settings
def validate_zip(path,size):
    if size>settings.MAX_ZIP_SIZE_MB*1024*1024:return False,f'ZIP exceeds {settings.MAX_ZIP_SIZE_MB}MB limit'
    if not zipfile.is_zipfile(path): return False,'Invalid ZIP archive'
    with zipfile.ZipFile(path) as z:
        if len(z.infolist())>settings.MAX_ZIP_FILES:return False,'ZIP contains too many files'
        total=sum(i.file_size for i in z.infolist())
        if total>settings.MAX_EXTRACTED_SIZE_MB*1024*1024:return False,'Extracted project exceeds size limit'
        for i in z.infolist():
            p=Path(i.filename)
            if p.is_absolute() or i.filename.startswith(('/', '\\')) or '..' in p.parts or p.drive:return False,'ZIP contains an unsafe path'
            if len(p.parts)>20:return False,'ZIP directory depth is excessive'
    return True,''
def extract_zip(zip_path,extract_to):
    root=Path(extract_to).resolve(); root.mkdir(parents=True,exist_ok=True); files=[]
    with zipfile.ZipFile(zip_path) as z:
        for i in z.infolist():
            p=Path(i.filename)
            if i.is_dir() or p.parts[0]=='__MACOSX' or any(x in settings.SKIP_FOLDERS for x in p.parts) or p.suffix.lower() not in settings.SOURCE_EXTENSIONS: continue
            dest=(root/p).resolve()
            if root not in dest.parents: raise ValueError('Unsafe archive path')
            dest.parent.mkdir(parents=True,exist_ok=True)
            with z.open(i) as src, open(dest,'wb') as out: out.write(src.read())
            files.append(str(p))
    return len(files),files
def read_source_files(root):
    parts=[]; total=0
    for p in sorted(Path(root).rglob('*')):
        if not p.is_file() or p.suffix.lower() not in settings.SOURCE_EXTENSIONS or any(x in settings.SKIP_FOLDERS for x in p.parts): continue
        try: text=p.read_text(errors='replace'); text='\n'.join(text.splitlines()[:settings.MAX_LINES_PER_FILE])
        except OSError: continue
        chunk=f'\n--- FILE: {p.relative_to(root)} ---\n{text}\n'
        if total+len(chunk)>settings.MAX_CONTEXT_CHARS: break
        parts.append(chunk); total+=len(chunk)
    return ''.join(parts)
def get_file_tree(root): return '\n'.join(str(p.relative_to(root)) for p in sorted(Path(root).rglob('*')) if p.is_file())
def get_project_stats(root):
    files=list(Path(root).rglob('*')); return {'file_count':sum(p.is_file() for p in files),'total_lines':sum(len(p.read_text(errors='ignore').splitlines()) for p in files if p.is_file() and p.suffix in settings.SOURCE_EXTENSIONS)}
def save_doc_to_disk(project_id,name,content):
    d=settings.DOCS_DIR/f'project_{project_id}'; d.mkdir(parents=True,exist_ok=True); p=d/'README.md'; p.write_text(content); return str(p)
