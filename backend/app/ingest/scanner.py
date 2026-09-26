"""Walk a repository and extract readable source files for ingest."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from app.ingest.parsers import language_for

MAX_FILES = 8000
MAX_PARSE_BYTES = 400_000
SKIP_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    "dist",
    "build",
    ".next",
    ".turbo",
    "coverage",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "neo4j-data",
    "target",
    "vendor",
}
SKIP_NAMES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "Cargo.lock"}
SKIP_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".pdf",
    ".zip",
    ".gz",
    ".woff",
    ".woff2",
    ".ttf",
    ".pyc",
    ".map",
    ".exe",
    ".dll",
    ".so",
}


@dataclass(frozen=True)
class ExtractedFile:
    path: Path
    rel: str
    text: str
    readable: bool
    language: str
    sha256: str
    loc: int
    size: int


def list_files(root: Path) -> list[Path]:
    found: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        parts = path.relative_to(root).parts
        if any(part in SKIP_DIRS for part in parts):
            continue
        if path.name in SKIP_NAMES or path.suffix.lower() in SKIP_SUFFIXES:
            continue
        found.append(path)
    found.sort()
    return found


def extract_file(root: Path, path: Path) -> ExtractedFile:
    rel = path.relative_to(root).as_posix()
    size = path.stat().st_size
    text, readable = _read(path, size)
    digest_src = text.encode("utf-8") if readable else path.name.encode()
    return ExtractedFile(
        path=path,
        rel=rel,
        text=text,
        readable=readable,
        language=language_for(rel),
        sha256=hashlib.sha256(digest_src).hexdigest(),
        loc=text.count("\n") + 1 if text else 0,
        size=size,
    )


def extract_repository(root: Path) -> list[ExtractedFile]:
    return [extract_file(root, path) for path in list_files(root)]


def _read(path: Path, size: int) -> tuple[str, bool]:
    if size > MAX_PARSE_BYTES:
        return "", False
    try:
        return path.read_text(encoding="utf-8", errors="replace"), True
    except OSError:
        return "", False
