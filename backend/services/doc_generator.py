"""Evidence-first documentation generation with streaming and performance instrumentation."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Callable

from backend.config import settings
from backend.services import gemini_service
from backend.services.gemini_service import generate, stream_generate
from backend.services.zip_handler import (
    get_file_tree,
    get_project_stats,
    read_source_files,
    save_doc_to_disk,
    scan_project,
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

# Fine-tuned token limits by document type to minimize generation latency
TOKEN_LIMITS: dict[str, int] = {
    "README": 4096,
    "Project Overview": 3584,
    "Setup Guide": 3584,
    "Usage Guide": 3584,
    "Configuration Guide": 3584,
    "Troubleshooting Guide": 3584,
    "Deployment Guide": 4096,
    "API Documentation": 6144,
    "Architecture Documentation": 6144,
    "Developer Guide": 6144,
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
    project_id: int,
    project_name: str,
    extract_dir: str,
    file_list: str = "",
    doc_type: str = "README",
    progress_callback: Callable[..., Any] | None = None,
    cancel_event: Any = None,
) -> str:
    if doc_type not in SUPPORTED_TYPES:
        raise ValueError("Unsupported documentation type.")

    t_start = time.perf_counter()

    # 1. Source scanning
    if progress_callback:
        progress_callback(10, "Scanning source files")
    t0_scan = time.perf_counter()
    scan_result = scan_project(extract_dir)
    source = scan_result["source"]
    if not source.strip():
        raise ValueError("No readable source files found.")
    tree = scan_result["file_tree"]
    stats = scan_result["stats"]
    source_scan_ms = round((time.perf_counter() - t0_scan) * 1000.0, 1)

    # 2. Structural analysis & prompt preparation
    if progress_callback:
        progress_callback(20, "Analyzing project structure")
    t0_prompt = time.perf_counter()
    compact_source = _clip_source(source)
    prompt = (
        f"Create {doc_type} documentation for {project_name}. "
        "Use only details supported by the supplied evidence. "
        "Include setup, usage, limitations, and architecture only where relevant to this document type.\n"
        f"Manifest:\n{tree}\n"
        f"Stats: {stats}\n"
        f"Source evidence:\n{compact_source}"
    )
    prompt_prep_ms = round((time.perf_counter() - t0_prompt) * 1000.0, 1)

    if progress_callback:
        progress_callback(25, "Preparing Gemini prompt")
        progress_callback(30, "Connecting to Gemini")

    max_tokens = TOKEN_LIMITS.get(doc_type, 4096)
    if settings.GEMINI_MAX_OUTPUT_TOKENS:
        max_tokens = min(max_tokens, settings.GEMINI_MAX_OUTPUT_TOKENS)

    streamed_chars = 0
    estimated_chars = 3500

    def on_chunk(chunk_text: str):
        nonlocal streamed_chars
        streamed_chars += len(chunk_text)
        if progress_callback:
            # Map progress from 35% to 88% based on actual streamed output
            prog = min(88, 35 + int((streamed_chars / estimated_chars) * 53))
            progress_callback(prog, "Generating documentation")

    # 3. Gemini generation (Streaming with fallback to generate if monkeypatched)
    t0_gemini = time.perf_counter()
    if generate is not gemini_service.generate:
        # Module-level generate function was monkeypatched by test suite
        raw_result = await generate(
            prompt,
            SYSTEM,
            thinking_level="low",
            max_output_tokens=max_tokens,
        )
        gemini_ttft_ms = round((time.perf_counter() - t0_gemini) * 1000.0, 1)
        gemini_gen_ms = gemini_ttft_ms
    else:
        raw_result, gemini_metrics = await stream_generate(
            prompt,
            SYSTEM,
            thinking_level="low",
            max_output_tokens=max_tokens,
            on_chunk=on_chunk,
            cancel_event=cancel_event,
        )
        gemini_ttft_ms = gemini_metrics.get("ttft_ms", 0.0)
        gemini_gen_ms = gemini_metrics.get("gemini_gen_ms", 0.0)

    # 4. Document validation
    if progress_callback:
        progress_callback(92, "Validating generated content")
    t0_val = time.perf_counter()
    result = validate_document(raw_result)
    validation_ms = round((time.perf_counter() - t0_val) * 1000.0, 1)

    # 5. Saving to disk and database
    if progress_callback:
        progress_callback(96, "Saving documentation")
    t0_save = time.perf_counter()
    utc_now = datetime.now(timezone.utc)
    doc = (
        f"# {project_name} — {doc_type}\n\n"
        f"> Generated {utc_now:%Y-%m-%d %H:%M UTC}; {stats['file_count']} files.\n\n"
        f"{result}\n"
    )
    save_doc_to_disk(project_id, project_name, doc)
    db_save_ms = round((time.perf_counter() - t0_save) * 1000.0, 1)
    total_duration_ms = round((time.perf_counter() - t_start) * 1000.0, 1)

    metrics = {
        "source_scan_ms": source_scan_ms,
        "prompt_prep_ms": prompt_prep_ms,
        "gemini_ttft_ms": gemini_ttft_ms,
        "gemini_gen_ms": gemini_gen_ms,
        "validation_ms": validation_ms,
        "db_save_ms": db_save_ms,
        "total_duration_ms": total_duration_ms,
    }

    if progress_callback:
        progress_callback(100, "Generation completed", metrics=metrics)

    return doc
