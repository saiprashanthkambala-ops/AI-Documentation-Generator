"""Structured chat assistant for editing generated documentation."""

from __future__ import annotations

import json
import re
from typing import Any

from backend.config import settings
from backend.services.gemini_service import generate
from backend.services.zip_handler import get_file_tree, read_source_files


SYSTEM_PROMPT = """
You are a conversational documentation editing assistant.
You edit ONLY the generated Markdown document. Never edit the uploaded source code.

Return valid JSON only with these keys:
reply, operation, summary, target, replacement

Allowed operations:
NO_CHANGE, REMOVE_TEXT, REMOVE_SECTION, REPLACE_TEXT, REWRITE_SECTION,
RENAME_HEADING, ADD_AFTER, ADD_BEFORE, APPEND

Safe-edit rules:
- Copy target EXACTLY from the current documentation for any operation that needs a target.
- Never invent target text.
- ADD_AFTER/ADD_BEFORE require an exact unique anchor from the current documentation.
- APPEND uses an empty target.
- replacement contains only new Markdown.
- Make the smallest possible change; do not rewrite unrelated content.
- For factual additions, use only the supplied source evidence.
- If the request is ambiguous or unsupported by evidence, return NO_CHANGE and explain.
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
        "REWRITE_SECTION", "RENAME_HEADING", "ADD_AFTER", "ADD_BEFORE", "APPEND",
    }
    operation = str(data.get("operation", "NO_CHANGE")).strip().upper()
    if operation not in allowed:
        operation = "NO_CHANGE"
    target = str(data.get("target", ""))
    replacement = str(data.get("replacement", ""))
    if operation == "NO_CHANGE":
        target = ""
        replacement = ""
    return {
        "reply": str(data.get("reply", "")).strip()
        or "I understood your request, but I could not prepare a safe documentation change.",
        "operation": operation,
        "summary": str(data.get("summary", "")).strip() or "No documentation change proposed.",
        "target": target,
        "replacement": replacement,
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
        "Prepare the best safe response to the latest user message."
    )
    parsed = _extract_json(await generate(prompt, SYSTEM_PROMPT))
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
