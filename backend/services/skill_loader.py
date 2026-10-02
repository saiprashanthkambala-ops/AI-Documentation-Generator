"""Load the application's documentation skill instructions."""

from __future__ import annotations

from pathlib import Path


SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"
DOCUMENTATION_DEFAULT_FORMAT_SKILL = (
    SKILLS_DIR / "documentation-default-format" / "SKILL.md"
)


def load_documentation_default_format_skill() -> str:
    """Return the canonical documentation skill used by the API chatbot."""
    try:
        content = DOCUMENTATION_DEFAULT_FORMAT_SKILL.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError(
            f"Documentation skill is unavailable: {DOCUMENTATION_DEFAULT_FORMAT_SKILL}"
        ) from exc
    if not content:
        raise RuntimeError("Documentation skill file is empty.")
    return content
