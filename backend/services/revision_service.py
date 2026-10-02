"""Persistent documentation revision/session helpers."""

from __future__ import annotations

import json
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.database.models import DocumentationRevision, DocumentationSession, Project


def _stack(value: str | None) -> list[int]:
    try:
        parsed = json.loads(value or "[]")
        return [int(x) for x in parsed]
    except (ValueError, TypeError, json.JSONDecodeError):
        return []


def _save_stacks(session: DocumentationSession, undo: list[int], redo: list[int]) -> None:
    session.undo_stack = json.dumps(undo)
    session.redo_stack = json.dumps(redo)
    session.updated_at = datetime.utcnow()


def ensure_session(project: Project, db: Session, bootstrap: bool = True) -> DocumentationSession:
    session = (
        db.query(DocumentationSession)
        .filter_by(project_id=project.id)
        .first()
    )
    if session is None:
        session = DocumentationSession(
            project_id=project.id,
            current_revision_id=None,
            undo_stack="[]",
            redo_stack="[]",
        )
        db.add(session)
        db.flush()

    if bootstrap and session.current_revision_id is None and project.generated_documentation:
        revision = DocumentationRevision(
            project_id=project.id,
            version_number=1,
            parent_revision_id=None,
            content=project.generated_documentation,
            operation="GENERATE",
            change_summary="Initial documentation revision",
        )
        db.add(revision)
        db.flush()
        session.current_revision_id = revision.id
        session.undo_stack = "[]"
        session.redo_stack = "[]"
        session.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(session)

    return session


def current_revision(project: Project, db: Session) -> DocumentationRevision:
    session = ensure_session(project, db)
    if not session.current_revision_id:
        raise HTTPException(status_code=400, detail="Generate documentation before using the assistant.")
    revision = db.query(DocumentationRevision).filter_by(
        id=session.current_revision_id,
        project_id=project.id,
    ).first()
    if revision is None:
        raise HTTPException(status_code=500, detail="Current documentation revision is unavailable.")
    return revision


def create_revision(
    project: Project,
    db: Session,
    content: str,
    operation: str,
    summary: str,
) -> DocumentationRevision:
    session = ensure_session(project, db, bootstrap=False)
    parent_id = session.current_revision_id
    version_number = db.query(DocumentationRevision).filter_by(project_id=project.id).count() + 1
    revision = DocumentationRevision(
        project_id=project.id,
        version_number=version_number,
        parent_revision_id=parent_id,
        content=content,
        operation=operation,
        change_summary=summary,
    )
    db.add(revision)
    db.flush()

    undo = _stack(session.undo_stack)
    redo: list[int] = []
    if parent_id:
        undo.append(parent_id)
    session.current_revision_id = revision.id
    _save_stacks(session, undo, redo)

    project.generated_documentation = content
    db.commit()
    db.refresh(revision)
    return revision


def _move(
    project: Project,
    db: Session,
    direction: str,
) -> tuple[DocumentationRevision, DocumentationSession]:
    session = ensure_session(project, db)
    current_id = session.current_revision_id
    if not current_id:
        raise HTTPException(status_code=400, detail="No documentation revision is available.")

    undo = _stack(session.undo_stack)
    redo = _stack(session.redo_stack)

    if direction == "undo":
        if not undo:
            raise HTTPException(status_code=409, detail="Nothing to undo.")
        target_id = undo.pop()
        redo.append(current_id)
    else:
        if not redo:
            raise HTTPException(status_code=409, detail="Nothing to redo.")
        target_id = redo.pop()
        undo.append(current_id)

    target = db.query(DocumentationRevision).filter_by(
        id=target_id,
        project_id=project.id,
    ).first()
    if target is None:
        raise HTTPException(status_code=500, detail="Revision history is inconsistent.")

    session.current_revision_id = target.id
    _save_stacks(session, undo, redo)
    project.generated_documentation = target.content
    db.commit()
    db.refresh(session)
    return target, session


def undo(project: Project, db: Session):
    return _move(project, db, "undo")


def redo(project: Project, db: Session):
    return _move(project, db, "redo")


def restore_revision(
    project: Project,
    db: Session,
    revision_id: int,
):
    session = ensure_session(project, db)
    current_id = session.current_revision_id
    target = db.query(DocumentationRevision).filter_by(
        id=revision_id,
        project_id=project.id,
    ).first()
    if target is None:
        raise HTTPException(status_code=404, detail="Revision not found.")
    if current_id == target.id:
        return target, session

    undo_stack = _stack(session.undo_stack)
    redo_stack = _stack(session.redo_stack)
    if current_id:
        undo_stack.append(current_id)
    session.current_revision_id = target.id
    _save_stacks(session, undo_stack, [])
    project.generated_documentation = target.content
    db.commit()
    db.refresh(session)
    return target, session


def serialize_revision(revision: DocumentationRevision, current_id: int | None) -> dict:
    return {
        "id": revision.id,
        "version_number": revision.version_number,
        "parent_revision_id": revision.parent_revision_id,
        "operation": revision.operation,
        "summary": revision.change_summary,
        "created_at": revision.created_at,
        "current": revision.id == current_id,
    }


def serialize_message(message) -> dict:
    proposal = None
    if message.proposal_json:
        try:
            proposal = json.loads(message.proposal_json)
        except (ValueError, TypeError, json.JSONDecodeError):
            proposal = None
    return {
        "id": message.id,
        "role": message.role,
        "content": message.content,
        "proposal": proposal,
        "revision_id": message.revision_id,
        "created_at": message.created_at,
    }


def can_undo(session: DocumentationSession) -> bool:
    return bool(_stack(session.undo_stack))


def can_redo(session: DocumentationSession) -> bool:
    return bool(_stack(session.redo_stack))
