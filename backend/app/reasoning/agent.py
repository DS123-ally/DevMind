"""Agent workflow: intent → Neo4j → code neighborhood → briefing → extract memory.

This is a LangGraph-style state machine. Each step is a named node. The briefing
is still produced only from graph facts.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.config import Settings
from app.reasoning.engine import _from_neighborhood, _from_overview
from app.reasoning.intent import detect_intent
from app.reasoning.llm import compose
from app.reasoning.query import lucene_query


def ask(store, settings: Settings, repo_id: str, question: str, requested_mode: str | None) -> dict:
    steps: list[dict] = []
    intent = detect_intent(question, requested_mode)
    steps.append({"id": "intent", "label": "Intent detection", "detail": intent["kind"]})

    if not store.get_project(repo_id):
        raise LookupError("Repository not found")

    tokens = list(intent["tokens"])
    if intent["kind"] in {"technologies", "why_technology"} and "redis" not in tokens:
        tokens = tokens or ["technology"]
    if intent["kind"] == "overview":
        graph = store.overview(repo_id)
        facts = _from_overview(question, intent["mode"], repo_id, graph, matched=True)
        steps.append({"id": "memory", "label": "Neo4j overview", "detail": "repository subgraph"})
    else:
        seeds = [seed for seed in store.search(repo_id, tokens, lucene_query(tokens)) if seed["label"] != "Repository"]
        if not seeds:
            graph = store.overview(repo_id)
            facts = _from_overview(question, intent["mode"], repo_id, graph, matched=False)
            steps.append({"id": "memory", "label": "Neo4j retrieval", "detail": "no token match; overview"})
        else:
            seed_ids = [seed["id"] for seed in seeds[:8]]
            graph = store.neighborhood(repo_id, seed_ids)
            facts = _from_neighborhood(question, intent["mode"], graph, seed_ids)
            steps.append({"id": "memory", "label": "Neo4j retrieval", "detail": ", ".join(seed["name"] for seed in seeds[:5])})

    steps.append(
        {
            "id": "code",
            "label": "Code search",
            "detail": ", ".join(f"{item.name} ({item.file})" for item in facts.symbols[:4]) or "no symbols in this subgraph",
        }
    )
    steps.append({"id": "context", "label": "Context builder", "detail": f"{len(facts.evidence)} graph relationships"})
    briefing = compose(settings, facts)
    steps.append({"id": "llm", "label": "Reasoning", "detail": briefing.get("voice") or "graph"})
    briefing["question"] = question
    briefing["mode"] = intent["mode"]
    briefing["intent"] = intent["kind"]
    briefing["steps"] = steps
    briefing["path"] = store.why_path(repo_id, tokens)
    briefing["citations"] = _citations(facts)
    briefing["id"] = store.save_briefing(repo_id, briefing, facts.anchor_ids[:12])
    briefing["createdAt"] = datetime.now(timezone.utc).isoformat()
    extracted = _extract_memory(store, settings, repo_id, question, briefing, facts.anchor_ids)
    if extracted:
        steps.append({"id": "write", "label": "Update Neo4j", "detail": extracted})
        briefing["extracted"] = extracted
    else:
        steps.append({"id": "write", "label": "Update Neo4j", "detail": "Conversation stored"})
        briefing["extracted"] = None
    briefing["steps"] = steps
    return briefing


def _citations(facts) -> list[dict]:
    rows: list[dict] = []
    for symbol in facts.symbols[:6]:
        rows.append({"kind": symbol.kind, "name": symbol.name, "path": symbol.file, "line": symbol.line})
    for file in facts.files[:6]:
        rows.append({"kind": "file", "name": file.path, "path": file.path, "line": None})
    for issue in facts.issues[:4]:
        rows.append({"kind": "issue", "name": issue.key, "path": issue.title, "line": None})
    seen = set()
    unique = []
    for row in rows:
        key = (row["kind"], row["name"], row["path"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique


def _extract_memory(store, settings: Settings, repo_id: str, question: str, briefing: dict, about_ids: list[str]) -> str | None:
    lowered = question.lower()
    if not any(marker in lowered for marker in ("remember", "we decided", "decision:", "record that")):
        return None
    rationale = " ".join(briefing.get("why") or briefing.get("what") or [])
    if not rationale:
        rationale = question
    title = question.strip().rstrip("?")[:180]
    try:
        store.add_decision(repo_id, title, rationale[:4000], "accepted", about_ids[:8], None)
    except LookupError:
        return None
    return f"Decision recorded: {title}"


def read_source(root: str, relative: str, limit: int = 80_000) -> str:
    path = Path(root) / relative
    if not path.is_file():
        raise FileNotFoundError(relative)
    resolved = path.resolve()
    base = Path(root).resolve()
    if base not in resolved.parents and resolved != base:
        raise PermissionError("Path is outside the repository")
    return resolved.read_text(encoding="utf-8", errors="replace")[:limit]
