"""Theme metadata helpers for documentation rendering and export."""

from __future__ import annotations

import json
import re
from typing import Any

DEFAULT_THEME: dict[str, str] = {
    "primary": "#4f46e5",
    "secondary": "#3730a3",
    "accent": "#7c3aed",
    "text": "#243447",
    "muted": "#64748b",
    "surface": "#f8fafc",
    "surface_alt": "#eef2ff",
    "border": "#d8e0ea",
    "code_bg": "#101827",
    "code_text": "#e2e8f0",
}

THEME_KEYS = tuple(DEFAULT_THEME.keys())
THEME_PATTERN = re.compile(r"^<!-- DOC_THEME:\s*(\{.*\})\s*-->\s*$", re.MULTILINE)
HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def normalize_theme(value: Any) -> dict[str, str]:
    """Validate a theme and merge it over the safe default palette."""
    candidate = value if isinstance(value, dict) else {}
    normalized = dict(DEFAULT_THEME)
    for key in THEME_KEYS:
        raw = candidate.get(key)
        if isinstance(raw, str) and HEX_RE.fullmatch(raw.strip()):
            normalized[key] = raw.strip().lower()
    return normalized


def extract_theme(markdown: str) -> dict[str, str]:
    """Read theme metadata embedded in generated Markdown."""
    if not markdown:
        return dict(DEFAULT_THEME)
    match = THEME_PATTERN.search(markdown)
    if not match:
        return dict(DEFAULT_THEME)
    try:
        data = json.loads(match.group(1))
    except (ValueError, TypeError, json.JSONDecodeError):
        return dict(DEFAULT_THEME)
    return normalize_theme(data)


def strip_theme_metadata(markdown: str) -> str:
    """Remove the hidden theme comment before human-facing Markdown rendering."""
    return THEME_PATTERN.sub("", markdown, count=1).lstrip("\n")


def apply_theme(markdown: str, theme: Any) -> str:
    """Replace the existing theme metadata with a validated palette."""
    cleaned = strip_theme_metadata(markdown).rstrip()
    normalized = normalize_theme(theme)
    payload = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
    return f"<!-- DOC_THEME: {payload} -->\n\n{cleaned}\n"
