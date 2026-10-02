"""Evidence-first documentation generation."""
from datetime import datetime

from backend.config import settings
from backend.services.gemini_service import generate
from backend.services.zip_handler import (
    get_file_tree,
    get_project_stats,
    read_source_files,
    save_doc_to_disk,
)

SYSTEM = (
    "You are an evidence-first technical writer. Use only supplied project evidence. "
    "Never invent technologies, APIs, authentication, deployment, or behavior. "
    "Mark unknown details as unknown. Return Markdown."
)

SUPPORTED_TYPES = {
    "README",
    "Project Overview",
    "Setup Guide",
    "API Documentation",
    "Architecture Documentation",
    "Developer Guide",
    "Configuration Guide",
    "Usage Guide",
    "Deployment Guide",
    "Troubleshooting Guide",
}


def validate_document(text: str) -> str:
    if not text or len(text.strip()) < 80:
        raise ValueError("Gemini returned insufficient documentation.")
    return text if text.lstrip().startswith("#") else "# Documentation\n\n" + text


def _clip_source(source: str) -> str:
    limit = max(8000, int(settings.MAX_CONTEXT_CHARS))
    if len(source) <= limit:
        return source
    return (
        source[:limit]
        + "\n\n[Source evidence truncated for latency and request-size control. "
        "Use the file tree and available evidence above; do not invent omitted details.]"
    )


async def generate_documentation(
    project_id,
    project_name,
    extract_dir,
    file_list="",
    doc_type="README",
):
    if doc_type not in SUPPORTED_TYPES:
        raise ValueError("Unsupported documentation type.")

    source = read_source_files(extract_dir)
    if not source.strip():
        raise ValueError("No readable source files found.")

    stats = get_project_stats(extract_dir)
    tree = get_file_tree(extract_dir)
    compact_source = _clip_source(source)

    prompt = (
        f"Create {doc_type} documentation for {project_name}. "
        "Use only details supported by the supplied evidence. "
        "Include setup, usage, limitations, and architecture only where relevant to this document type.\n"
        f"Manifest:\n{tree}\n"
        f"Stats: {stats}\n"
        f"Source evidence:\n{compact_source}"
    )

    result = validate_document(
        await generate(
            prompt,
            SYSTEM,
            thinking_level="low",
            max_output_tokens=min(settings.GEMINI_MAX_OUTPUT_TOKENS, 6144),
        )
    )

    doc = (
        f"# {project_name} — {doc_type}\n\n"
        f"> Generated {datetime.utcnow():%Y-%m-%d %H:%M UTC}; {stats['file_count']} files.\n\n"
        f"{result}\n"
    )
    save_doc_to_disk(project_id, project_name, doc)
    return doc
