from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database.models import Base, Project
from backend.services.documentation_assistant import apply_proposal
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
