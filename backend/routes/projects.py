"""
API routes for the Documentation Assistant.
Handles ZIP upload, documentation generation, history, and download.
"""

import os
import shutil
import json
import difflib
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, Query
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy.orm import Session

from backend.config import settings
from backend.database.db import get_db
from backend.database.models import Project, ProjectVersion, DocumentationVersion, ChangeReport
from backend.services.intelligence import manifest, compare, impact, documentation_plan
from backend.schemas.schemas import (
    GenerateResponse,
    MessageResponse,
    ProjectDetail,
    ProjectSummary,
    ProjectUploadResponse,
)
from backend.services.doc_generator import generate_documentation
from backend.services.zip_handler import extract_zip, validate_zip
from backend.services.gemini_service import ProviderError, status as gemini_status
from backend.services.document_exporter import ExportError, markdown_to_jpg, markdown_to_pdf
from backend.services.revision_service import create_revision, current_revision

router = APIRouter(prefix="/api", tags=["Projects"])


@router.get("/gemini/status")
async def gemini_status_route():
    return await gemini_status()


# ---------- Upload ZIP ----------

@router.post("/upload", response_model=ProjectUploadResponse)
async def upload_project(
    name: str = Form(...),
    zip_file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """
    Module 1 & 2: Upload a ZIP file and extract source files.
    Does NOT clone GitHub — user must upload ZIP manually.
    """
    if not name.strip():
        raise HTTPException(status_code=400, detail="Project name is required")

    if not zip_file.filename or not zip_file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Please upload a .zip file")

    # Save ZIP temporarily
    project = Project(name=name.strip(), status="uploaded")
    db.add(project)
    db.commit()
    db.refresh(project)

    project_dir = settings.UPLOADS_DIR / f"project_{project.id}"
    project_dir.mkdir(parents=True, exist_ok=True)
    zip_path = project_dir / "upload.zip"

    try:
        content = await zip_file.read()
        with open(zip_path, "wb") as f:
            f.write(content)

        # Validate ZIP
        valid, error_msg = validate_zip(str(zip_path), len(content))
        if not valid:
            db.delete(project)
            db.commit()
            raise HTTPException(status_code=400, detail=error_msg)

        # Extract files
        extract_dir = project_dir / "source"
        file_count, file_list = extract_zip(str(zip_path), str(extract_dir))

        if file_count == 0:
            shutil.rmtree(project_dir, ignore_errors=True)
            db.delete(project)
            db.commit()
            raise HTTPException(
                status_code=400,
                detail="No source files found in ZIP. Include .py, .md, or .txt files.",
            )

        # Update project record
        project.file_count = file_count
        project.file_list = ", ".join(file_list[:20])  # Store first 20 for display
        if len(file_list) > 20:
            project.file_list += f" ... and {len(file_list) - 20} more"
        db.commit()
        db.refresh(project)
        current_manifest = manifest(str(extract_dir))
        import json, hashlib
        snapshot_hash = hashlib.sha256(json.dumps(current_manifest, sort_keys=True).encode()).hexdigest()
        version = ProjectVersion(project_id=project.id, manifest=json.dumps(current_manifest), snapshot_hash=snapshot_hash)
        db.add(version); db.commit()

        return ProjectUploadResponse(
            id=project.id,
            name=project.name,
            upload_date=project.upload_date,
            file_count=project.file_count,
            file_list=project.file_list,
            status=project.status,
            message=f"ZIP uploaded and {file_count} source files extracted successfully.",
        )

    except HTTPException:
        raise
    except Exception as e:
        shutil.rmtree(project_dir, ignore_errors=True)
        db.delete(project)
        db.commit()
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


@router.post('/projects/{project_id}/versions/upload')
async def upload_project_version(project_id:int, zip_file:UploadFile=File(...), db:Session=Depends(get_db)):
    project=db.query(Project).filter_by(id=project_id).first()
    if not project: raise HTTPException(404,'Project not found')
    if not zip_file.filename or not zip_file.filename.lower().endswith('.zip'): raise HTTPException(400,'Please upload a .zip file')
    base=settings.UPLOADS_DIR/f'project_{project_id}'; version_no=db.query(ProjectVersion).filter_by(project_id=project_id).count()+1; work=base/f'version_{version_no}'; work.mkdir(parents=True,exist_ok=True); path=work/'upload.zip'
    try:
        data=await zip_file.read(); path.write_bytes(data); valid,error=validate_zip(str(path),len(data))
        if not valid: raise HTTPException(400,error)
        source=work/'source'; count,files=extract_zip(str(path),str(source))
        if not count: raise HTTPException(400,'No supported source files found.')
        current=manifest(str(source)); snap=__import__('hashlib').sha256(json.dumps(current,sort_keys=True).encode()).hexdigest(); previous=db.query(ProjectVersion).filter_by(project_id=project_id).order_by(ProjectVersion.created_at.desc()).first()
        v=ProjectVersion(project_id=project_id,manifest=json.dumps(current),snapshot_hash=snap); db.add(v); db.commit(); db.refresh(v)
        result={'version_id':v.id,'file_count':count,'changes':None,'impact':None}
        if previous:
            changes=compare(json.loads(previous.manifest),current); imp=impact(changes); report=ChangeReport(project_id=project_id,previous_version_id=previous.id,current_version_id=v.id,changes=json.dumps(changes),impact=json.dumps(imp)); db.add(report)
            for doc in db.query(DocumentationVersion).filter_by(project_id=project_id,status='CURRENT').all():
                if imp['affected']: doc.status='OUTDATED'
            db.commit(); result.update(changes=changes,impact=imp,change_report_id=report.id)
        return result
    except HTTPException: raise
    except Exception:
        shutil.rmtree(work,ignore_errors=True); raise HTTPException(500,'Version upload failed safely.')

# ---------- Generate Documentation ----------

@router.post("/projects/{project_id}/generate", response_model=GenerateResponse)
async def generate_docs(project_id: int, doc_type: str = Query('README'), db: Session = Depends(get_db)):
    """
    Module 3 & 4: Read source code and generate AI documentation.
  """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")


    extract_dir = settings.UPLOADS_DIR / f"project_{project_id}" / "source"
    if not extract_dir.exists():
        raise HTTPException(status_code=400, detail="Source files not found. Re-upload the ZIP.")

    prior_docs = db.query(DocumentationVersion).filter_by(project_id=project.id).all()
    for old_doc in prior_docs:
        if old_doc.status in ('CURRENT','OUTDATED','PARTIALLY_AFFECTED'): old_doc.status='GENERATING'
    db.commit()
    try:
        documentation = await generate_documentation(
            project_id=project.id,
            project_name=project.name,
            extract_dir=str(extract_dir),
            file_list=project.file_list or "",
            doc_type=doc_type,
        )

        project.generated_documentation = documentation
        project.status = "completed"
        for old_doc in prior_docs: old_doc.status='SUPERSEDED'
        latest = db.query(ProjectVersion).filter_by(project_id=project.id).order_by(ProjectVersion.created_at.desc()).first()
        db.add(DocumentationVersion(project_id=project.id, project_version_id=latest.id if latest else None, content=documentation, doc_type=doc_type, status='CURRENT'))
        db.commit()
        create_revision(
            project,
            db,
            documentation,
            "GENERATE",
            "Documentation regenerated by Gemini.",
        )
        db.refresh(project)

        word_count = len(documentation.split())

        return GenerateResponse(
            id=project.id,
            name=project.name,
            status=project.status,
            message=f"Documentation generated! ({word_count:,} words)",
            generated_documentation=documentation,
            word_count=word_count,
            section_count=7,
        )

    except ValueError as e:
        project.status = "failed"
        for old_doc in prior_docs: old_doc.status='FAILED'
        db.commit()
        raise HTTPException(status_code=400, detail=str(e))
    except TimeoutError as e:
        project.status = "failed"
        for old_doc in prior_docs: old_doc.status='FAILED'
        db.commit()
        raise HTTPException(status_code=504, detail=str(e))
    except ProviderError as e:
        project.status = "failed"; [setattr(d,'status','FAILED') for d in prior_docs]; db.commit()
        raise HTTPException(status_code=503, detail={"code":e.code,"message":e.message})
    except Exception:
        project.status = "failed"; db.commit()
        raise HTTPException(status_code=500, detail="Generation failed safely. Please try again.")


# ---------- History ----------

@router.get("/projects", response_model=list[ProjectSummary])
def list_projects(db: Session = Depends(get_db)):
    """Get all uploaded projects (history page)."""
    projects = db.query(Project).order_by(Project.upload_date.desc()).all()

    return [
        ProjectSummary(
            id=p.id,
            name=p.name,
            upload_date=p.upload_date,
            file_count=p.file_count,
            status=p.status,
            has_documentation=bool(p.generated_documentation),
        )
        for p in projects
    ]


@router.get("/projects/{project_id}", response_model=ProjectDetail)
def get_project(project_id: int, db: Session = Depends(get_db)):
    """Get project details with full generated documentation."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


# ---------- Download / Export ----------

def _project_for_download(project_id: int, db: Session) -> Project:
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not project.generated_documentation:
        raise HTTPException(status_code=400, detail="No documentation generated yet.")
    return project


def _safe_project_name(project: Project) -> str:
    return "".join(
        c if c.isalnum() or c in ("-", "_") else "_" for c in project.name
    )


@router.get("/projects/{project_id}/download")
def download_documentation(project_id: int, db: Session = Depends(get_db)):
    """Download the currently selected documentation revision as Markdown."""
    project = _project_for_download(project_id, db)
    revision = current_revision(project, db)
    filename = f"{_safe_project_name(project)}_README.md"
    return PlainTextResponse(
        content=revision.content,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/projects/{project_id}/download/pdf")
def download_documentation_pdf(project_id: int, db: Session = Depends(get_db)):
    """Render the currently selected documentation revision as PDF."""
    project = _project_for_download(project_id, db)
    revision = current_revision(project, db)
    try:
        payload = markdown_to_pdf(revision.content, project.name)
    except ExportError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception:
        raise HTTPException(status_code=500, detail="PDF export failed safely.")
    filename = f"{_safe_project_name(project)}_Documentation.pdf"
    return Response(
        content=payload,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/projects/{project_id}/download/jpg")
def download_documentation_jpg(project_id: int, db: Session = Depends(get_db)):
    """Render the currently selected documentation revision as one long JPG."""
    project = _project_for_download(project_id, db)
    revision = current_revision(project, db)
    try:
        payload = markdown_to_jpg(revision.content, project.name)
    except ExportError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception:
        raise HTTPException(status_code=500, detail="JPG export failed safely.")
    filename = f"{_safe_project_name(project)}_Documentation.jpg"
    return Response(
        content=payload,
        media_type="image/jpeg",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get('/projects/{project_id}/versions')
def project_versions(project_id: int, db: Session = Depends(get_db)):
    rows=db.query(ProjectVersion).filter_by(project_id=project_id).order_by(ProjectVersion.created_at.desc()).all()
    return [{'id':r.id,'created_at':r.created_at,'snapshot_hash':r.snapshot_hash,'manifest':__import__('json').loads(r.manifest)} for r in rows]

@router.get('/projects/{project_id}/documentation-versions')
def documentation_versions(project_id: int, db: Session = Depends(get_db)):
    rows=db.query(DocumentationVersion).filter_by(project_id=project_id).order_by(DocumentationVersion.created_at.desc()).all()
    return [{'id':r.id,'project_version_id':r.project_version_id,'doc_type':r.doc_type,'status':r.status,'created_at':r.created_at,'content':r.content} for r in rows]

@router.get('/projects/{project_id}/changes')
def project_changes(project_id: int, db: Session = Depends(get_db)):
    rows=db.query(ProjectVersion).filter_by(project_id=project_id).order_by(ProjectVersion.created_at.asc()).all()
    if len(rows)<2: return {'changes':{'added':[],'modified':[],'removed':[],'unchanged':[]},'impact':{'affected':[],'reasons':{}},'message':'At least two project versions are required.'}
    changes=compare(json.loads(rows[-2].manifest),json.loads(rows[-1].manifest))
    result={'previous_version_id':rows[-2].id,'current_version_id':rows[-1].id,'changes':changes,'impact':impact(changes)}
    report=ChangeReport(project_id=project_id,previous_version_id=rows[-2].id,current_version_id=rows[-1].id,changes=json.dumps(changes),impact=json.dumps(result['impact']))
    db.add(report); db.commit(); result['report_id']=report.id
    return result

@router.get('/projects/{project_id}/change-reports')
def change_reports(project_id: int, db: Session = Depends(get_db)):
    rows=db.query(ChangeReport).filter_by(project_id=project_id).order_by(ChangeReport.created_at.desc()).all()
    return [{'id':r.id,'previous_version_id':r.previous_version_id,'current_version_id':r.current_version_id,'changes':json.loads(r.changes),'impact':json.loads(r.impact),'created_at':r.created_at} for r in rows]

@router.post('/projects/{project_id}/maintenance')
async def maintenance(project_id: int, db: Session = Depends(get_db)):
    project=db.query(Project).filter_by(id=project_id).first()
    if not project: raise HTTPException(404,'Project not found')
    docs=db.query(DocumentationVersion).filter_by(project_id=project_id).order_by(DocumentationVersion.created_at.desc()).all()
    if not docs: raise HTTPException(400,'Generate documentation before maintenance.')
    changes=project_changes(project_id,db)
    affected=set(changes.get('impact',{}).get('affected',[])); old=docs[0]
    if not affected: return {'status':'CURRENT','message':'No documentation changes are required.','documentation_version_id':old.id}
    extract_dir=settings.UPLOADS_DIR/f'project_{project_id}'/'source'
    try:
        updated=await generate_documentation(project_id,project.name,str(extract_dir),project.file_list or '',old.doc_type)
    except ProviderError as e: raise HTTPException(503,{'code':e.code,'message':e.message})
    latest=db.query(ProjectVersion).filter_by(project_id=project_id).order_by(ProjectVersion.created_at.desc()).first()
    new=DocumentationVersion(project_id=project_id,project_version_id=latest.id,content=updated,doc_type=old.doc_type,status='DRAFT')
    db.add(new); db.commit()
    return {'status':'DRAFT','documentation_version_id':new.id,'affected':sorted(affected),'diff':list(difflib.unified_diff(old.content.splitlines(),updated.splitlines(),lineterm=''))}

@router.get('/projects/{project_id}/documentation-diff/{new_id}')
def documentation_diff(project_id:int,new_id:int,db:Session=Depends(get_db)):
    new=db.query(DocumentationVersion).filter_by(id=new_id,project_id=project_id).first()
    if not new: raise HTTPException(404,'Documentation version not found')
    old=db.query(DocumentationVersion).filter(DocumentationVersion.project_id==project_id,DocumentationVersion.id<new_id).order_by(DocumentationVersion.id.desc()).first()
    if not old: return {'old_version_id':None,'new_version_id':new.id,'diff':[]}
    return {'old_version_id':old.id,'new_version_id':new.id,'diff':list(difflib.unified_diff(old.content.splitlines(),new.content.splitlines(),fromfile='previous',tofile='proposed',lineterm=''))}

@router.post('/projects/{project_id}/documentation/{doc_id}/decision')
def documentation_decision(project_id:int,doc_id:int,decision:str,db:Session=Depends(get_db)):
    doc=db.query(DocumentationVersion).filter_by(id=doc_id,project_id=project_id).first()
    if not doc or decision not in ('approve','reject'): raise HTTPException(400,'Invalid documentation or decision.')
    doc.status='CURRENT' if decision=='approve' else 'REJECTED'; db.commit()
    if decision=='approve':
        db.query(DocumentationVersion).filter(DocumentationVersion.project_id==project_id,DocumentationVersion.id!=doc.id,DocumentationVersion.status.in_(['CURRENT','OUTDATED','PARTIALLY_AFFECTED','GENERATING'])).update({'status':'SUPERSEDED'})
        p=db.query(Project).filter_by(id=project_id).first(); p.generated_documentation=doc.content; db.commit()
    return {'id':doc.id,'status':doc.status}

# ---------- Delete ----------

@router.delete("/projects/{project_id}", response_model=MessageResponse)
def delete_project(project_id: int, db: Session = Depends(get_db)):
    """Delete a project and its files."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Remove uploaded files from disk
    project_dir = settings.UPLOADS_DIR / f"project_{project_id}"
    if project_dir.exists():
        shutil.rmtree(project_dir, ignore_errors=True)

    docs_dir = settings.DOCS_DIR / f"project_{project_id}"
    if docs_dir.exists():
        shutil.rmtree(docs_dir, ignore_errors=True)

    db.delete(project)
    db.commit()

    return MessageResponse(message=f"Project '{project.name}' deleted.")
