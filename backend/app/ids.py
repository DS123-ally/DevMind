"""Stable graph identifiers. The same path always maps to the same node."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

_NAMESPACE = uuid.UUID("c0ffee00-0000-4000-8000-000000000001")


def repo_id_for(path: Path) -> str:
    key = os.path.normcase(str(path.resolve()))
    return str(uuid.uuid5(_NAMESPACE, f"devmind:repo:{key}"))


def node_id(repo_id: str, kind: str, key: str) -> str:
    return f"{repo_id}:{kind}:{key}"


def person_key(name: str, email: str | None = None) -> str:
    raw = (email or name).strip().lower()
    return raw or "unknown"
