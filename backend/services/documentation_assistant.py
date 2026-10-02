"""Structured chat assistant for editing generated documentation."""

from __future__ import annotations

import json
import re
from typing import Any

from backend.config import settings
from backend.services.gemini_service import generate
from backend.services.document_theme import DEFAULT_THEME
from backend.services.document_theme import apply_theme
from backend.services.zip_handler import get_file_tree, read_source_files


SYSTEM_PROMPT = """
You are a conversational documentation editing assistant.
You edit ONLY the generated Markdown document. Never edit the uploaded source code.

Return valid JSON only with these keys:
reply, operation, summary, target, replacement, theme

Allowed operations:
NO_CHANGE, REMOVE_TEXT, REMOVE_SECTION, REPLACE_TEXT, REWRITE_SECTION,
RENAME_HEADING, ADD_AFTER, ADD_BEFORE, APPEND, REWRITE_DOCUMENT, STYLE_DOCUMENT

Natural conversation rules:
- Interpret normal conversational requests instead of rejecting them for being brief.
- "increase the content", "make it more detailed", "add more content", "expand this document" => REWRITE_DOCUMENT.
- "make the document smaller", "shorten it", "reduce the content", "make it concise" => REWRITE_DOCUMENT.
- "humanize it", "make it more natural", "make it easier to read" => REWRITE_DOCUMENT.
- Requests to change document colours/colors or try a different colour theme => STYLE_DOCUMENT.
- A short follow-up such as "try" should use the immediately preceding styling request and choose a tasteful professional palette when no exact colours are specified.
- STYLE_DOCUMENT changes presentation only and must preserve the wording and structure. Return a theme object with the keys: primary, secondary, accent, text, muted, surface, surface_alt, border, code_bg, code_text. Use six-digit hex values.
- "change the colours", "change the colors", "make it more colorful", "try a different colour theme" => STYLE_DOCUMENT.
- A short follow-up such as "try" should use the immediately preceding styling request in the recent chat context and choose a professional accessible palette when no exact colors were provided.
- STYLE_DOCUMENT changes presentation only; it must preserve the document wording and structure. Return a "theme" object with these hex keys: primary, secondary, accent, text, muted, surface, surface_alt, border, code_bg, code_text.
- "change the colours", "change the colors", "make it more colorful", "try a different colour theme" => STYLE_DOCUMENT.
- A short follow-up such as "try" should use the immediately preceding styling request in the conversation and choose a professional accessible palette when no exact colors were provided.
- STYLE_DOCUMENT changes presentation only; it must preserve the document wording and structure. Return a "theme" object with these hex keys: primary, secondary, accent, text, muted, surface, surface_alt, border, code_bg, code_text.
- When the user asks for a whole-document transformation, target MUST be empty and replacement MUST be the COMPLETE revised Markdown document.
- For whole-document transformations, preserve all important factual information from the current document, improve structure/readability, and use supplied source evidence for any new factual details.
- Do not ask the user to specify a section when the requested transformation clearly applies to the entire document.
- For a document-size request, interpret "size" from context: usually content length/detail, not page dimensions. Do not change PDF paper size unless explicitly requested.
- "change the project name X into Y" => use REPLACE_TEXT or RENAME_HEADING with an exact current target.
- For STYLE_DOCUMENT, target MUST be empty and replacement MUST be empty; return only the requested theme palette.
- For STYLE_DOCUMENT, target MUST be empty and replacement MUST be empty; return only the requested theme palette.
- Copy target EXACTLY from the current documentation for operations that require a target.
- Never invent target text.
- ADD_AFTER/ADD_BEFORE require an exact unique anchor from the current documentation.
- APPEND uses an empty target.
- replacement contains only new Markdown.
- For factual additions, use only the supplied source evidence.
- NO_CHANGE is appropriate only when the request is genuinely impossible, unsafe, or lacks enough context to perform the requested transformation.
- Do not output JSON inside Markdown fences.
""".strip()


def _extract_json(raw: str) -> dict[str, Any] | None:
    text = raw.strip()
    fence = chr(96) * 3
    text = re.sub(r"^" + re.escape(fence) + r"(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*" + re.escape(fence) + r"$", "", text)
    try:
        value = json.loads(text)
    except (ValueError, TypeError):
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            return None
        try:
            value = json.loads(match.group(0))
        except (ValueError, TypeError):
            return None
    return value if isinstance(value, dict) else None


def _normalize(data: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "NO_CHANGE", "REMOVE_TEXT", "REMOVE_SECTION", "REPLACE_TEXT",
        "REWRITE_SECTION", "RENAME_HEADING", "ADD_AFTER", "ADD_BEFORE",
        "APPEND", "REWRITE_DOCUMENT", "STYLE_DOCUMENT",
    }
    operation = str(data.get("operation", "NO_CHANGE")).strip().upper()
    if operation not in allowed:
        operation = "NO_CHANGE"
    target = str(data.get("target", ""))
    replacement = str(data.get("replacement", ""))
    theme = data.get("theme") if isinstance(data.get("theme"), dict) else {}
    if operation == "NO_CHANGE":
        target = ""
        replacement = ""
    elif operation in {"REWRITE_DOCUMENT", "STYLE_DOCUMENT"}:
        target = ""
    return {
        "reply": str(data.get("reply", "")).strip()
        or "I understood your request, but I could not prepare a safe documentation change.",
        "operation": operation,
        "summary": str(data.get("summary", "")).strip() or "No documentation change proposed.",
        "target": target,
        "replacement": replacement,
        "theme": theme if operation == "STYLE_DOCUMENT" else {},
    }


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "\n\n[Context truncated safely.]"


def _conversation_text(messages: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for item in messages[-12:]:
        lines.append(
            f"{str(item.get('role', 'user')).upper()}: {item.get('content', '').strip()}"
        )
        if item.get("proposal"):
            lines.append("PROPOSAL: " + json.dumps(item["proposal"], ensure_ascii=False))
    return "\n".join(lines)


async def propose_change(
    *,
    project_name: str,
    current_document: str,
    source_dir: str,
    conversation: list[dict[str, Any]],
) -> dict[str, Any]:
    source = read_source_files(source_dir)
    tree = get_file_tree(source_dir)
    prompt = (
        f"PROJECT: {project_name}\n\n"
        "CURRENT DOCUMENTATION:\n"
        f"{_clip(current_document, settings.MAX_CONTEXT_CHARS)}\n\n"
        "SOURCE FILE TREE:\n"
        f"{_clip(tree, 12000)}\n\n"
        "SOURCE EVIDENCE:\n"
        f"{_clip(source, 18000)}\n\n"
        "RECENT CHAT:\n"
        f"{_conversation_text(conversation)}\n\n"
        "Prepare the best safe response to the latest user message. If the latest message is a short follow-up, use the recent chat context to resolve what it refers to."
    )
    # Chat is primarily an instruction-following task. Gemini documents the
    # LOW thinking level as the latency/cost-oriented setting for chat.
    parsed = _extract_json(
        await generate(
            prompt,
            SYSTEM_PROMPT,
            thinking_level="low",
            max_output_tokens=4096,
        )
    )
    if parsed is None:
        return {
            "reply": "I understood your request, but I could not prepare a safe structured change. Please try again.",
            "operation": "NO_CHANGE",
            "summary": "No safe change produced.",
            "target": "",
            "replacement": "",
        }
    return _normalize(parsed)


def apply_proposal(
    markdown: str, proposal: dict[str, Any]
) -> tuple[str, dict[str, str]]:
    """Apply an exact, validated documentation patch."""
    operation = str(proposal.get("operation", "NO_CHANGE")).upper()
    target = str(proposal.get("target", ""))
    replacement = str(proposal.get("replacement", ""))

    if operation == "NO_CHANGE":
        raise ValueError("There is no applicable change in this assistant response.")

    if operation == "STYLE_DOCUMENT":
        from backend.services.document_theme import apply_theme
        theme = proposal.get("theme")
        if not isinstance(theme, dict):
            raise ValueError("The assistant did not provide a valid document color theme.")
        updated = apply_theme(markdown, theme)
        return updated, {
            "operation": operation,
            "target": "",
            "replacement": "",
        }

    if operation == "STYLE_DOCUMENT":
        theme = proposal.get("theme")
        if not isinstance(theme, dict):
            raise ValueError("The assistant did not provide a valid document color theme.")
        updated = apply_theme(markdown, theme)
        return updated, {
            "operation": operation,
            "target": "",
            "replacement": "",
        }

    if operation == "REWRITE_DOCUMENT":
        if not replacement.strip():
            raise ValueError("The proposed full-document content is empty.")
        updated = replacement.strip() + "\n"
        if not updated.strip().startswith("#"):
            raise ValueError("The proposed full-document content must be Markdown with a heading.")
        return updated, {
            "operation": operation,
            "target": "",
            "replacement": replacement.strip(),
        }

    if operation == "APPEND":
        if not replacement.strip():
            raise ValueError("The proposed content is empty.")
        updated = (
            markdown.rstrip()
            + ("\n\n" if markdown.strip() else "")
            + replacement.strip()
            + "\n"
        )
        return updated, {
            "operation": operation,
            "target": "",
            "replacement": replacement.strip(),
        }

    if not target:
        raise ValueError("The assistant did not provide an exact target.")

    occurrences = markdown.count(target)
    if occurrences == 0:
        raise ValueError(
            "That proposed target is no longer present in the current revision."
        )
    if occurrences > 1:
        raise ValueError(
            "That target appears multiple times; ask the assistant to identify the exact one."
        )

    if operation in {"REMOVE_TEXT", "REMOVE_SECTION"}:
        replacement_text = ""
    elif operation in {"REPLACE_TEXT", "REWRITE_SECTION", "RENAME_HEADING"}:
        replacement_text = replacement
    elif operation == "ADD_AFTER":
        if not replacement.strip():
            raise ValueError("The proposed content is empty.")
        replacement_text = target + "\n\n" + replacement.strip()
    elif operation == "ADD_BEFORE":
        if not replacement.strip():
            raise ValueError("The proposed content is empty.")
        replacement_text = replacement.strip() + "\n\n" + target
    else:
        raise ValueError("Unsupported documentation change operation.")

    updated = markdown.replace(target, replacement_text, 1)
    if not updated.strip():
        raise ValueError("The change would remove the entire document.")

    return updated, {
        "operation": operation,
        "target": target,
        "replacement": (
            replacement
            if operation not in {"REMOVE_TEXT", "REMOVE_SECTION"}
            else ""
        ),
    }
