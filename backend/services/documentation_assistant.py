"""Structured chat assistant for answering questions and editing generated documentation."""

from __future__ import annotations

import json
import re
from typing import Any

from backend.config import settings
from backend.services.document_theme import apply_theme, ensure_distinct_theme, extract_theme
from backend.services.gemini_service import generate
from backend.services.skill_loader import load_documentation_default_format_skill
from backend.services.zip_handler import get_file_tree, read_source_files

SYSTEM_PROMPT = """
You are a helpful, conversational documentation editing assistant.
You have two responsibilities:
1. Answer questions about the project, architecture, code, and documentation clearly and conversationally.
2. Propose precise, safe edits to the generated Markdown document when requested. Never edit the uploaded source code.

Return valid JSON only with these keys:
reply, operation, summary, target, replacement, theme

Allowed operations:
NO_CHANGE, REMOVE_TEXT, REMOVE_SECTION, REPLACE_TEXT, REWRITE_SECTION,
RENAME_HEADING, ADD_AFTER, ADD_BEFORE, APPEND, REWRITE_DOCUMENT, STYLE_DOCUMENT

Rules for Informational & Conversational Questions:
- If the user asks a question, requests an explanation, asks for an overview, asks about specific files, greets you, or does not ask to change the document:
  - operation MUST be "NO_CHANGE"
  - summary MUST be "Informational response."
  - target MUST be ""
  - replacement MUST be ""
  - theme MUST be {}
  - reply MUST be your complete, helpful, well-formatted Markdown answer directly addressing the user's question!
- Examples: "Explain this project", "How does auth work?", "What does main.py do?", "What sections are in this doc?", "Hello!" => All use operation: NO_CHANGE and put the comprehensive explanation in reply.

Rules for Document Modification Requests:
- Interpret normal conversational requests instead of rejecting them for being brief:
  - "increase the content", "make it more detailed", "expand this document", "add more detail" => REWRITE_DOCUMENT.
  - "make the document smaller", "shorten it", "reduce content", "make it concise" => REWRITE_DOCUMENT.
  - "humanize it", "make it more natural", "make it easier to read" => REWRITE_DOCUMENT.
  - "change the colours", "change colors", "make it more colorful", "try a different colour theme" => STYLE_DOCUMENT.
  - Short follow-up such as "try" or "make it dark blue" uses recent chat context to pick an appropriate palette.
- STYLE_DOCUMENT changes presentation only and preserves structure. Return a theme object with: primary, secondary, accent, text, muted, surface, surface_alt, border, code_bg, code_text. Use six-digit hex codes. Target and replacement must be empty.
- When the user asks for a whole-document transformation (REWRITE_DOCUMENT), target MUST be empty and replacement MUST be the COMPLETE revised Markdown document starting with a heading.
- For targeted edits (REPLACE_TEXT, REWRITE_SECTION, RENAME_HEADING, REMOVE_TEXT, REMOVE_SECTION, ADD_AFTER, ADD_BEFORE):
  - target MUST be an EXACT verbatim substring copied from CURRENT DOCUMENTATION.
  - ADD_AFTER / ADD_BEFORE require an exact anchor from the current document.
  - APPEND uses an empty target and puts new Markdown in replacement.
- For factual additions, use only the supplied source evidence. Never invent technologies or behavior.
- Do not wrap JSON inside Markdown fences.
""".strip() + "\n\n--- ACTIVE DOCUMENTATION SKILL ---\n" + load_documentation_default_format_skill() + "\n--- END ACTIVE DOCUMENTATION SKILL ---"


def _extract_json(raw: str) -> dict[str, Any] | None:
    text = raw.strip()
    if not text:
        return None

    # Strip markdown code fences if present
    fence = chr(96) * 3
    cleaned_text = re.sub(r"^" + re.escape(fence) + r"(?:json)?\s*", "", text, flags=re.I)
    cleaned_text = re.sub(r"\s*" + re.escape(fence) + r"$", "", cleaned_text).strip()

    # 1. Direct JSON parse
    try:
        val = json.loads(cleaned_text)
        if isinstance(val, dict):
            return val
    except (ValueError, TypeError, json.JSONDecodeError):
        pass

    # 2. Extract balanced or first-to-last brace substring
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        candidate = text[first_brace : last_brace + 1]
        try:
            val = json.loads(candidate)
            if isinstance(val, dict):
                return val
        except (ValueError, TypeError, json.JSONDecodeError):
            # Clean trailing commas
            candidate_cleaned = re.sub(r",\s*([}\]])", r"\1", candidate)
            try:
                val = json.loads(candidate_cleaned)
                if isinstance(val, dict):
                    return val
            except (ValueError, TypeError, json.JSONDecodeError):
                pass

    # 3. Fallback for conversational / natural-language responses:
    # If Gemini returned a plain text answer instead of JSON, treat it as the reply so the user gets their answer!
    plain = cleaned_text if cleaned_text else text
    if plain:
        return {
            "reply": plain,
            "operation": "NO_CHANGE",
            "summary": "Informational response.",
            "target": "",
            "replacement": "",
            "theme": {},
        }

    return None


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
    for item in messages[-8:]:
        role = str(item.get("role", "user")).upper()
        content = item.get("content", "").strip()
        lines.append(f"{role}: {content}")
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
        "SOURCE FILE TREE (trimmed for fast editing requests):\n"
        f"{_clip(tree, 8000)}\n\n"
        "SOURCE EVIDENCE (relevant excerpts only):\n"
        f"{_clip(source, 12000)}\n\n"
        "RECENT CHAT:\n"
        f"{_conversation_text(conversation)}\n\n"
        "Prepare the best safe response to the latest user message. If the latest message is a question or explanation request, explain clearly with operation NO_CHANGE. If it is a change request, prepare the exact structured change."
    )

    raw_response = await generate(
        prompt,
        SYSTEM_PROMPT,
        thinking_level="low",
        max_output_tokens=4096,
        response_mime_type="application/json",
    )
    parsed = _extract_json(raw_response)
    if parsed is None:
        return {
            "reply": "I understood your request, but I could not prepare a safe structured change. Please try again.",
            "operation": "NO_CHANGE",
            "summary": "No safe change produced.",
            "target": "",
            "replacement": "",
        }
    result = _normalize(parsed)
    if result["operation"] == "STYLE_DOCUMENT":
        result["theme"] = ensure_distinct_theme(
            result.get("theme", {}),
            extract_theme(current_document),
        )
    return result


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
