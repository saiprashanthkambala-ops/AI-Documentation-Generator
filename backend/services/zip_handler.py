"""Safe ZIP ingestion, single-pass project scanning, and file manifest utilities."""

from __future__ import annotations

import os
import zipfile
from pathlib import Path
from typing import Any

from backend.config import settings

# High-priority architecture and configuration files for prompt context.
_PRIORITY_FILENAMES = {
    "readme.md",
    "readme.txt",
    "readme",
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "setup.py",
    "cargo.toml",
    "go.mod",
    "pom.xml",
    "dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "alembic.ini",
}

_PRIORITY_KEYWORDS = ("main", "app", "index", "server", "router", "route", "model", "schema", "service")


def validate_zip(path: str | Path, size: int) -> tuple[bool, str]:
    limit_bytes = settings.MAX_ZIP_SIZE_MB * 1024 * 1024
    if size > limit_bytes:
        return False, f"ZIP exceeds {settings.MAX_ZIP_SIZE_MB}MB limit"
    if not zipfile.is_zipfile(path):
        return False, "Invalid ZIP archive"
    with zipfile.ZipFile(path) as z:
        infolist = z.infolist()
        if len(infolist) > settings.MAX_ZIP_FILES:
            return False, "ZIP contains too many files"
        total = sum(i.file_size for i in infolist)
        if total > settings.MAX_EXTRACTED_SIZE_MB * 1024 * 1024:
            return False, "Extracted project exceeds size limit"
        for i in infolist:
            p = Path(i.filename)
            if p.is_absolute() or i.filename.startswith(("/", "\\")) or ".." in p.parts:
                return False, "ZIP contains an unsafe path"
            if len(p.parts) > 20:
                return False, "ZIP directory depth is excessive"
    return True, ""


def extract_zip(zip_path: str | Path, extract_to: str | Path) -> tuple[int, list[str]]:
    root = Path(extract_to).resolve()
    root.mkdir(parents=True, exist_ok=True)
    files: list[str] = []
    with zipfile.ZipFile(zip_path) as z:
        for i in z.infolist():
            p = Path(i.filename)
            if (
                i.is_dir()
                or p.parts[0] == "__MACOSX"
                or any(x in settings.SKIP_FOLDERS for x in p.parts)
                or p.suffix.lower() not in settings.SOURCE_EXTENSIONS
            ):
                continue
            dest = (root / p).resolve()
            if root not in dest.parents:
                raise ValueError("Unsafe archive path")
            dest.parent.mkdir(parents=True, exist_ok=True)
            with z.open(i) as src, open(dest, "wb") as out:
                out.write(src.read())
            files.append(str(p))
    return len(files), files


def scan_project(root: str | Path) -> dict[str, Any]:
    """Single-pass filesystem traversal extracting tree, stats, and prioritized source evidence."""
    root_path = Path(root).resolve()
    if not root_path.exists():
        return {
            "file_count": 0,
            "total_lines": 0,
            "file_tree": "",
            "source": "",
            "files": [],
            "stats": {"file_count": 0, "total_lines": 0},
        }

    all_files: list[Path] = []
    source_files: list[Path] = []
    total_lines = 0

    # Prune skipped folders during iteration to avoid walking deep build/cache directories.
    for dirpath, dirnames, filenames in os.walk(root_path):
        dirnames[:] = [d for d in dirnames if d not in settings.SKIP_FOLDERS and not d.startswith(".")]
        current_dir = Path(dirpath)
        for fname in filenames:
            if fname.startswith("."):
                continue
            fpath = current_dir / fname
            all_files.append(fpath)
            if fpath.suffix.lower() in settings.SOURCE_EXTENSIONS:
                source_files.append(fpath)
                try:
                    line_count = sum(1 for _ in fpath.open("r", encoding="utf-8", errors="ignore"))
                    total_lines += line_count
                except OSError:
                    pass

    # Sort files deterministically
    all_files.sort(key=lambda p: str(p.relative_to(root_path)).replace("\\", "/"))
    rel_files = [str(p.relative_to(root_path)).replace("\\", "/") for p in all_files]
    file_tree = "\n".join(rel_files)
    file_count = len(all_files)

    # Rank source files by architectural value
    def file_rank(path: Path) -> int:
        rel_lower = str(path.relative_to(root_path)).replace("\\", "/").lower()
        base_lower = path.name.lower()
        if base_lower in _PRIORITY_FILENAMES:
            return 0
        if any(kw in rel_lower for kw in _PRIORITY_KEYWORDS):
            return 1
        if path.suffix.lower() in {".py", ".ts", ".js", ".go", ".rs", ".java"}:
            return 2
        return 3

    source_files.sort(key=lambda p: (file_rank(p), str(p.relative_to(root_path)).replace("\\", "/")))

    parts: list[str] = []
    total_chars = 0
    max_chars = max(8000, int(settings.MAX_CONTEXT_CHARS))
    max_lines = max(20, int(settings.MAX_LINES_PER_FILE))

    for p in source_files:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
            lines = text.splitlines()[:max_lines]
            text = "\n".join(lines)
        except OSError:
            continue

        rel = str(p.relative_to(root_path)).replace("\\", "/")
        chunk = f"\n--- FILE: {rel} ---\n{text}\n"
        if total_chars + len(chunk) > max_chars:
            remaining = max(0, max_chars - total_chars)
            if remaining > 200:
                parts.append(chunk[:remaining] + "\n[...truncated...]\n")
            break
        parts.append(chunk)
        total_chars += len(chunk)

    source_text = "".join(parts)
    stats = {"file_count": file_count, "total_lines": total_lines}

    return {
        "file_count": file_count,
        "total_lines": total_lines,
        "file_tree": file_tree,
        "source": source_text,
        "files": rel_files,
        "stats": stats,
    }


def read_source_files(root: str | Path) -> str:
    return scan_project(root)["source"]


def get_file_tree(root: str | Path) -> str:
    return scan_project(root)["file_tree"]


def get_project_stats(root: str | Path) -> dict[str, int]:
    return scan_project(root)["stats"]


def save_doc_to_disk(project_id: int, name: str, content: str) -> str:
    d = settings.DOCS_DIR / f"project_{project_id}"
    d.mkdir(parents=True, exist_ok=True)
    p = d / "README.md"
    p.write_text(content, encoding="utf-8")
    return str(p)
