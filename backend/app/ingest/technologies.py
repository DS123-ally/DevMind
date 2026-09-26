"""Detect libraries and runtimes from manifests. These become Technology nodes."""

from __future__ import annotations

import json
import re

CATEGORIES = {
    "fastapi": "web",
    "flask": "web",
    "django": "web",
    "starlette": "web",
    "uvicorn": "web",
    "react": "ui",
    "react-dom": "ui",
    "vite": "tooling",
    "neo4j": "graph",
    "stripe": "payments",
    "httpx": "http",
    "pydantic": "data",
    "typescript": "language",
    "pytest": "test",
    "python": "runtime",
    "node": "runtime",
}

_REQUIREMENT = re.compile(r"^[A-Za-z0-9_.-]+")
_FROM = re.compile(r"^FROM\s+([^\s:@]+)", re.IGNORECASE | re.MULTILINE)
_IMAGE = re.compile(r"""image:\s*['"]?([^\s:'"]+)""", re.IGNORECASE)


def category_for(name: str) -> str:
    return CATEGORIES.get(normalize_package(name), "library")


def normalize_package(name: str) -> str:
    cleaned = name.strip().lower()
    if cleaned.startswith("@"):
        return cleaned
    return cleaned.split("/")[-1].replace("_", "-")


def technologies_in_manifest(path: str, text: str) -> list[tuple[str, str]]:
    """Return (package name, manifest path) pairs."""
    lowered = path.lower()
    name = lowered.rsplit("/", 1)[-1]
    found: list[str] = []
    if name in {"requirements.txt", "requirements-dev.txt"} or name.startswith("requirements"):
        found.extend(_requirements(text))
    elif name == "package.json":
        found.extend(_package_json(text))
    elif name in {"pyproject.toml", "pipfile"}:
        found.extend(_quoted_packages(text))
    elif name == "dockerfile" or name.endswith(".dockerfile"):
        found.extend(_images(text, _FROM))
    elif name in {"docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"}:
        found.extend(_images(text, _IMAGE))
    return [(package, path) for package in _unique(found)]


def import_matches_technology(module: str, packages: set[str]) -> str | None:
    if not module or module.startswith("."):
        return None
    root = module.split("/")[0].split(".")[0]
    normalized = normalize_package(root)
    if normalized in packages:
        return normalized
    return None


def _requirements(text: str) -> list[str]:
    packages: list[str] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-") or line.startswith("["):
            continue
        match = _REQUIREMENT.match(re.split(r"[<>=!~;\[]", line, maxsplit=1)[0].strip())
        if match:
            packages.append(match.group(0))
    return packages


def _package_json(text: str) -> list[str]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    packages: list[str] = []
    for key in ("dependencies", "devDependencies", "peerDependencies"):
        block = data.get(key) or {}
        if isinstance(block, dict):
            packages.extend(str(name) for name in block)
    return packages


def _quoted_packages(text: str) -> list[str]:
    return re.findall(r"""['"]([A-Za-z0-9_.-]+)(?:[<>=~\[][^'"]*)?['"]""", text)


def _images(text: str, pattern: re.Pattern[str]) -> list[str]:
    names: list[str] = []
    for match in pattern.finditer(text):
        image = match.group(1).rsplit("/", 1)[-1].lower()
        if image and image not in {"scratch", "alpine"}:
            names.append(image)
    return names


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        key = normalize_package(item)
        if key and key not in seen:
            seen.add(key)
            ordered.append(item)
    return ordered
