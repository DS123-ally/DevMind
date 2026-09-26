"""Load `.devmind/memory.json`, the explicit home for issues, errors, and pull requests."""

from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass
class MemoryBundle:
    issues: list[dict] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    solutions: list[dict] = field(default_factory=list)
    pull_requests: list[dict] = field(default_factory=list)
    decisions: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def load_memory(text: str) -> MemoryBundle:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return MemoryBundle(warnings=[f".devmind/memory.json is not valid JSON ({exc.msg})."])
    if not isinstance(data, dict):
        return MemoryBundle(warnings=[".devmind/memory.json must be an object."])
    return MemoryBundle(
        issues=_dicts(data.get("issues")),
        errors=_dicts(data.get("errors")),
        solutions=_dicts(data.get("solutions")),
        pull_requests=_dicts(data.get("pullRequests")),
        decisions=_dicts(data.get("decisions")),
    )


def _dicts(value: object) -> list[dict]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]
