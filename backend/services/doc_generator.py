from datetime import datetime
from backend.services.gemini_service import generate
from backend.services.zip_handler import read_source_files,get_file_tree,get_project_stats,save_doc_to_disk
SYSTEM='You are an evidence-first technical writer. Use only supplied project evidence. Never invent technologies, APIs, authentication, deployment, or behavior. Mark unknown details as unknown. Return Markdown.'
SUPPORTED_TYPES={'README','Project Overview','Setup Guide','API Documentation','Architecture Documentation','Developer Guide','Configuration Guide','Usage Guide','Deployment Guide','Troubleshooting Guide'}
def validate_document(text):
    if not text or len(text.strip()) < 80: raise ValueError('Gemini returned insufficient documentation.')
    return text if text.lstrip().startswith('#') else '# Documentation\n\n'+text
async def generate_documentation(project_id,project_name,extract_dir,file_list='',doc_type='README'):
    if doc_type not in SUPPORTED_TYPES: raise ValueError('Unsupported documentation type.')
    source=read_source_files(extract_dir)
    if not source.strip(): raise ValueError('No readable source files found.')
    stats=get_project_stats(extract_dir)
    prompt=f'''Create {doc_type} documentation for {project_name}. Include only details supported by this evidence. Include setup, usage, limitations, and architecture where relevant.\nManifest:\n{get_file_tree(extract_dir)}\nStats: {stats}\nSource evidence:\n{source}'''
    result=validate_document(await generate(prompt,SYSTEM))
    doc=f'# {project_name} — {doc_type}\n\n> Generated {datetime.utcnow():%Y-%m-%d %H:%M UTC}; {stats["file_count"]} files.\n\n{result}\n'
    save_doc_to_disk(project_id,project_name,doc); return doc
