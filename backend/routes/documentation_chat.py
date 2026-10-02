"""Chat and revision workspace routes."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.config import settings
from backend.database.db import get_db
from backend.database.models import ChatMessage, DocumentationRevision, Project
from backend.schemas.schemas import (
    ChatApplyRequest,
    ChatMessageResponse,
    ChatRequest,
    ChatResponse,
    RevisionActionResponse,
    RevisionSummary,
    WorkspaceResponse,
)
from backend.services.documentation_assistant import apply_proposal, propose_change
from backend.services.revision_service import (
    can_redo,
    can_undo,
    create_revision,
    current_revision,
    ensure_session,
    redo,
    restore_revision,
    serialize_message,
    serialize_revision,
    undo,
)
from backend.services.gemini_service import ProviderError


router = APIRouter(prefix="/api/projects", tags=["Documentation Assistant"])


def _project(project_id: int, db: Session) -> Project:
    value = db.query(Project).filter_by(id=project_id).first()
    if not value:
        raise HTTPException(status_code=404, detail="Project not found.")
    return value


def _conversation(db: Session, project_id: int) -> list[dict]:
    rows = (
        db.query(ChatMessage)
        .filter_by(project_id=project_id)
        .order_by(ChatMessage.created_at.asc())
        .all()
    )
    result = []
    for row in rows:
        proposal = None
        if row.proposal_json:
            try:
                proposal = json.loads(row.proposal_json)
            except (ValueError, TypeError, json.JSONDecodeError):
                proposal = None
        result.append({
            "role": row.role,
            "content": row.content,
            "proposal": proposal,
        })
    return result


def _action_payload(project: Project, db: Session, message: str) -> RevisionActionResponse:
    revision = current_revision(project, db)
    session = ensure_session(project, db)
    return RevisionActionResponse(
        current_revision_id=revision.id,
        current_documentation=revision.content,
        can_undo=can_undo(session),
        can_redo=can_redo(session),
        message=message,
    )


@router.get("/{project_id}/workspace", response_model=WorkspaceResponse)
def get_workspace(project_id: int, db: Session = Depends(get_db)):
    project = _project(project_id, db)
    revision = current_revision(project, db)
    session = ensure_session(project, db)
    revisions = (
        db.query(DocumentationRevision)
        .filter_by(project_id=project_id)
        .order_by(DocumentationRevision.created_at.desc())
        .limit(50)
        .all()
    )
    messages = (
        db.query(ChatMessage)
        .filter_by(project_id=project_id)
        .order_by(ChatMessage.created_at.asc())
        .limit(100)
        .all()
    )
    return WorkspaceResponse(
        project_id=project.id,
        project_name=project.name,
        current_revision_id=revision.id,
        current_documentation=revision.content,
        can_undo=can_undo(session),
        can_redo=can_redo(session),
        revisions=[RevisionSummary(**serialize_revision(r, revision.id)) for r in revisions],
        messages=[ChatMessageResponse(**serialize_message(m)) for m in messages],
    )


@router.post("/{project_id}/chat", response_model=ChatResponse)
async def chat(project_id: int, payload: ChatRequest, db: Session = Depends(get_db)):
    project = _project(project_id, db)
    revision = current_revision(project, db)

    user_message = payload.message.strip()
    if not user_message:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    user_row = ChatMessage(
        project_id=project.id,
        revision_id=revision.id,
        role="user",
        content=user_message,
    )
    db.add(user_row)
    db.commit()

    conversation = _conversation(db, project.id)
    try:
        proposal = await propose_change(
            project_name=project.name,
            current_document=revision.content,
            source_dir=str(settings.UPLOADS_DIR / f"project_{project.id}" / "source"),
            conversation=conversation,
        )
    except ProviderError as exc:
        assistant_text = f"I couldn't reach Gemini safely: {exc.message}"
        proposal = {
            "reply": assistant_text,
            "operation": "NO_CHANGE",
            "summary": "No change proposed.",
            "target": "",
            "replacement": "",
        }

    proposal["base_revision_id"] = revision.id
    assistant_row = ChatMessage(
        project_id=project.id,
        revision_id=revision.id,
        role="assistant",
        content=proposal["reply"],
        proposal_json=json.dumps(proposal, ensure_ascii=False),
    )
    db.add(assistant_row)
    db.commit()
    db.refresh(assistant_row)

    session = ensure_session(project, db)
    return ChatResponse(
        message=ChatMessageResponse(**serialize_message(assistant_row)),
        current_revision_id=revision.id,
        current_documentation=revision.content,
        can_undo=can_undo(session),
        can_redo=can_redo(session),
    )


@router.post("/{project_id}/chat/apply", response_model=ChatResponse)
def apply_chat_change(
    project_id: int,
    payload: ChatApplyRequest,
    db: Session = Depends(get_db),
):
    project = _project(project_id, db)
    assistant = (
        db.query(ChatMessage)
        .filter_by(id=payload.message_id, project_id=project.id, role="assistant")
        .first()
    )
    if assistant is None or not assistant.proposal_json:
        raise HTTPException(status_code=404, detail="Change proposal not found.")

    try:
        proposal = json.loads(assistant.proposal_json)
    except (ValueError, TypeError, json.JSONDecodeError):
        raise HTTPException(status_code=422, detail="Stored change proposal is invalid.")

    if proposal.get("status") == "APPLIED":
        raise HTTPException(status_code=409, detail="This change has already been applied.")

    revision = current_revision(project, db)
    base_revision_id = proposal.get("base_revision_id", assistant.revision_id)
    if base_revision_id != revision.id:
        raise HTTPException(
            status_code=409,
            detail="This proposal was created for an older document revision. Ask the assistant to prepare the change again.",
        )

    try:
        updated, _ = apply_proposal(revision.content, proposal)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    new_revision = create_revision(
        project,
        db,
        updated,
        proposal.get("operation", "EDIT"),
        proposal.get("summary", "Documentation updated by assistant."),
    )

    proposal["status"] = "APPLIED"
    proposal["applied_revision_id"] = new_revision.id
    proposal["applied_revision_version"] = new_revision.version_number
    assistant.proposal_json = json.dumps(proposal, ensure_ascii=False)
    db.commit()

    session = ensure_session(project, db)
    return ChatResponse(
        message=ChatMessageResponse(**serialize_message(assistant)),
        current_revision_id=new_revision.id,
        current_documentation=new_revision.content,
        can_undo=can_undo(session),
        can_redo=can_redo(session),
    )


@router.post("/{project_id}/chat/undo", response_model=RevisionActionResponse)
def undo_change(project_id: int, db: Session = Depends(get_db)):
    project = _project(project_id, db)
    revision, _ = undo(project, db)
    return _action_payload(project, db, f"Undo applied. Restored revision V{revision.version_number}.")


@router.post("/{project_id}/chat/redo", response_model=RevisionActionResponse)
def redo_change(project_id: int, db: Session = Depends(get_db)):
    project = _project(project_id, db)
    revision, _ = redo(project, db)
    return _action_payload(project, db, f"Redo applied. Restored revision V{revision.version_number}.")


@router.post("/{project_id}/chat/restore/{revision_id}", response_model=RevisionActionResponse)
def restore(project_id: int, revision_id: int, db: Session = Depends(get_db)):
    project = _project(project_id, db)
    revision, _ = restore_revision(project, db, revision_id)
    return _action_payload(project, db, f"Revision V{revision.version_number} restored.")
