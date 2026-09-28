"""Questions the UI can offer after a repository is loaded.

Each prompt is built from a real function, decision title, or ticket key.
"""

from __future__ import annotations

import re

_TICKET = re.compile(r"^[A-Z][A-Z0-9]+-\d+$")
_SKIP_FUNCTIONS = {"main", "init", "setup", "run", "index", "test"}


def suggested_questions(
    functions: list[str],
    decisions: list[str],
    issue_keys: list[str],
) -> list[dict]:
    questions: list[dict] = []
    for name in _function_names(functions)[:2]:
        questions.append({"text": f"What does {name} do?", "mode": "what"})
    for title in _decision_titles(decisions)[:2]:
        questions.append({"text": _why(title), "mode": "why"})
    for key in _ticket_keys(issue_keys)[:2]:
        questions.append({"text": f"What happened with {key}?", "mode": "why"})
    return questions


def _function_names(names: list[str]) -> list[str]:
    seen: set[str] = set()
    kept: list[str] = []
    for raw in names:
        name = re.sub(r"\(\)$", "", (raw or "").strip())
        key = name.lower()
        if not name or name.startswith("_") or key in _SKIP_FUNCTIONS or key in seen:
            continue
        if key.startswith("test_") or len(name) < 4:
            continue
        seen.add(key)
        kept.append(name)
    return kept


def _decision_titles(titles: list[str]) -> list[str]:
    seen: set[str] = set()
    kept: list[str] = []
    for raw in titles:
        title = " ".join((raw or "").split()).strip().rstrip(".")
        key = title.lower()
        if len(title) < 8 or key in seen:
            continue
        seen.add(key)
        kept.append(title)
    return kept


def _ticket_keys(keys: list[str]) -> list[str]:
    seen: set[str] = set()
    kept: list[str] = []
    for raw in keys:
        key = (raw or "").strip().upper()
        if not _TICKET.match(key) or key in seen:
            continue
        seen.add(key)
        kept.append(key)
    return kept


def _why(title: str) -> str:
    if title.lower().startswith("why "):
        return title if title.endswith("?") else f"{title}?"
    lowered = title[0].lower() + title[1:]
    return f"Why {lowered}?"
