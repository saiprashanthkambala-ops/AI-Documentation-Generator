from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database.models import Base, Project
from backend.services.documentation_assistant import SYSTEM_PROMPT, apply_proposal
from backend.services.revision_service import create_revision, current_revision, redo, undo


def test_remove_exact_text():
    original = "# Doc\n\nKeep this.\n\nRemove this sentence.\n\nKeep this too."
    updated, change = apply_proposal(
        original,
        {
            "operation": "REMOVE_TEXT",
            "target": "Remove this sentence.",
            "replacement": "",
        },
    )
    assert "Remove this sentence." not in updated
    assert "Keep this." in updated
    assert change["operation"] == "REMOVE_TEXT"


def test_replace_requires_unique_target():
    original = "# Doc\n\nSame text.\n\nSame text."
    try:
        apply_proposal(
            original,
            {
                "operation": "REPLACE_TEXT",
                "target": "Same text.",
                "replacement": "Changed.",
            },
        )
    except ValueError as exc:
        assert "multiple times" in str(exc)
    else:
        raise AssertionError("Expected ambiguous target to be rejected")


def test_add_after_anchor():
    original = "# Doc\n\n## Features\n\n- One"
    updated, _ = apply_proposal(
        original,
        {
            "operation": "ADD_AFTER",
            "target": "## Features",
            "replacement": "New paragraph.",
        },
    )
    assert "## Features\n\nNew paragraph." in updated


def test_revision_undo_redo_persists():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    project = Project(name="Revision Test", generated_documentation="# V1")
    db.add(project)
    db.commit()
    db.refresh(project)

    first = create_revision(project, db, "# V1", "GENERATE", "Initial")
    second = create_revision(project, db, "# V2", "REPLACE_TEXT", "Changed")
    third = create_revision(project, db, "# V3", "ADD_AFTER", "Added")

    assert first.version_number == 1
    assert second.version_number == 2
    assert third.version_number == 3
    assert current_revision(project, db).content == "# V3"

    restored, _ = undo(project, db)
    assert restored.version_number == 2
    assert current_revision(project, db).content == "# V2"

    restored, _ = redo(project, db)
    assert restored.version_number == 3
    assert current_revision(project, db).content == "# V3"

    db.close()



def test_rewrite_document_supports_broad_transformation():
    original = "# Crime Analysis\n\n## Overview\n\nA concise description."
    updated, change = apply_proposal(
        original,
        {
            "operation": "REWRITE_DOCUMENT",
            "target": "",
            "replacement": "# Crime Analysis\n\n## Overview\n\nA more detailed, human-readable description based on the supplied evidence.\n",
        },
    )
    assert updated.startswith("# Crime Analysis")
    assert "more detailed" in updated
    assert change["operation"] == "REWRITE_DOCUMENT"


def test_rewrite_document_rejects_non_markdown():
    try:
        apply_proposal(
            "# Doc",
            {
                "operation": "REWRITE_DOCUMENT",
                "target": "",
                "replacement": "plain text only",
            },
        )
    except ValueError as exc:
        assert "Markdown with a heading" in str(exc)
    else:
        raise AssertionError("Expected invalid full-document proposal to be rejected")



def test_style_document_adds_theme_metadata_without_changing_text():
    original = "# Crime Analysis\n\n## Problem Statement\n\nInvestigators need connected evidence."
    updated, change = apply_proposal(
        original,
        {
            "operation": "STYLE_DOCUMENT",
            "target": "",
            "replacement": "",
            "theme": {
                "primary": "#123456",
                "secondary": "#234567",
                "accent": "#345678",
                "text": "#456789",
                "muted": "#56789a",
                "surface": "#f4f7fb",
                "surface_alt": "#eaf0f7",
                "border": "#c8d2df",
                "code_bg": "#101827",
                "code_text": "#e2e8f0",
            },
        },
    )
    assert "Crime Analysis" in updated
    assert "Investigators need connected evidence." in updated
    assert "DOC_THEME:" in updated
    assert change["operation"] == "STYLE_DOCUMENT"


def test_style_document_rejects_missing_theme():
    try:
        apply_proposal(
            "# Doc",
            {
                "operation": "STYLE_DOCUMENT",
                "target": "",
                "replacement": "",
            },
        )
    except ValueError as exc:
        assert "color theme" in str(exc)
    else:
        raise AssertionError("Expected missing theme to be rejected")



def test_style_theme_is_not_silent_when_model_returns_current_palette():
    from backend.services.document_theme import DEFAULT_THEME, ALTERNATE_THEME, ensure_distinct_theme

    selected = ensure_distinct_theme(DEFAULT_THEME, DEFAULT_THEME)
    assert selected == ALTERNATE_THEME



def test_documentation_skill_is_loaded_into_api_chatbot_system_prompt():
    assert "documentation-default-format" in SYSTEM_PROMPT
    assert "PRECISION > CREATIVITY" in SYSTEM_PROMPT
    assert "Only the requested target and property differ" in SYSTEM_PROMPT
    assert "NO_CHANGE, REMOVE_TEXT, REMOVE_SECTION" in SYSTEM_PROMPT


def test_ui_contract_keeps_maintenance_out_and_profile_in():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    for page in ["index.html", "upload.html", "history.html", "documentation.html"]:
        content = (root / "frontend" / page).read_text(encoding="utf-8")
        assert "/maintenance" not in content

    profile = (root / "frontend" / "profile.html").read_text(encoding="utf-8")
    theme = (root / "frontend" / "js" / "theme.js").read_text(encoding="utf-8")
    assert "profile-trigger" in theme
    assert 'id="profileForm"' in profile


def test_ui_contract_has_cancellable_generation_and_chat_thinking_state():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    api = (root / "frontend" / "js" / "api.js").read_text(encoding="utf-8")
    documentation = (root / "frontend" / "js" / "documentation.js").read_text(encoding="utf-8")
    page = (root / "frontend" / "documentation.html").read_text(encoding="utf-8")

    assert "AbortController" in documentation
    assert "controller.abort()" in documentation
    assert "chatThinking" in documentation
    assert "loadingCancelBtn" in api
    assert "Generated Files" in page
