"""LangGraph agent: intent → graph retrieval → code retrieval → LLM response."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.config import Settings
from app.reasoning.engine import _conversation, _from_neighborhood, _from_overview
from app.reasoning.facts import BriefingFacts
from app.reasoning.intent import detect_intent
from app.reasoning.llm import compose
from app.reasoning.memory import apply_memory, extract_memory
from app.reasoning.query import lucene_query


class AgentState(TypedDict, total=False):
    question: str
    requested_mode: str | None
    repo_id: str
    intent: dict
    tokens: list[str]
    facts: BriefingFacts
    briefing: dict
    steps: list[dict]


def ask(store, settings: Settings, repo_id: str, question: str, requested_mode: str | None) -> dict:
    if not store.get_project(repo_id):
        raise LookupError("Repository not found")
    nodes = _nodes(store, settings)
    state: AgentState = {
        "question": question,
        "requested_mode": requested_mode,
        "repo_id": repo_id,
        "steps": [],
    }
    for name in (
        "intent_classification",
        "graph_retrieval",
        "code_retrieval",
        "llm_response",
        "memory_extraction",
        "neo4j_updates",
    ):
        state = {**state, **nodes[name](state)}
    briefing = json.loads(json.dumps(state["briefing"], default=str))
    return briefing


def _compile(store, settings: Settings):
    nodes = _nodes(store, settings)
    graph = StateGraph(AgentState)
    for name, fn in nodes.items():
        graph.add_node(name, fn)
    graph.add_edge(START, "intent_classification")
    graph.add_edge("intent_classification", "graph_retrieval")
    graph.add_edge("graph_retrieval", "code_retrieval")
    graph.add_edge("code_retrieval", "llm_response")
    graph.add_edge("llm_response", "memory_extraction")
    graph.add_edge("memory_extraction", "neo4j_updates")
    graph.add_edge("neo4j_updates", END)
    return graph.compile()


def _nodes(store, settings: Settings) -> dict:
    def intent_classification(state: AgentState) -> dict:
        intent = detect_intent(state["question"], state.get("requested_mode"))
        tokens = list(intent["tokens"])
        if intent["kind"] in {"technologies", "why_technology"} and "redis" not in tokens:
            tokens = tokens or ["technology"]
        return {
            "intent": intent,
            "tokens": tokens,
            "steps": _step(
                state,
                "intent",
                "Intent classification",
                f"{intent['kind']} · {intent['mode']}",
            ),
        }

    def graph_retrieval(state: AgentState) -> dict:
        intent = state["intent"]
        tokens = state["tokens"]
        repo_id = state["repo_id"]
        if intent["kind"] == "overview":
            graph = store.overview(repo_id)
            facts = _from_overview(state["question"], intent["mode"], repo_id, graph, matched=True)
            detail = "repository subgraph"
        else:
            seeds = [
                seed
                for seed in store.search(repo_id, tokens, lucene_query(tokens))
                if seed["label"] != "Repository"
            ]
            if not seeds:
                graph = store.overview(repo_id)
                facts = _from_overview(state["question"], intent["mode"], repo_id, graph, matched=False)
                detail = "no token match; overview"
            else:
                seed_ids = [seed["id"] for seed in seeds[:8]]
                graph = store.neighborhood(repo_id, seed_ids)
                facts = _from_neighborhood(state["question"], intent["mode"], graph, seed_ids)
                detail = ", ".join(seed["name"] for seed in seeds[:5])
        if not facts.conversations and hasattr(store, "recent_conversations"):
            facts.conversations = [
                _conversation(row) for row in store.recent_conversations(repo_id) if row.get("headline") or row.get("question")
            ]
        return {
            "facts": facts,
            "steps": _step(state, "graph", "Graph retrieval", detail),
        }

    def code_retrieval(state: AgentState) -> dict:
        facts = state["facts"]
        project = store.get_project(state["repo_id"]) or {}
        root = (project.get("repository") or {}).get("path") or ""
        snippets: list[dict] = []
        for symbol in facts.symbols[:6]:
            text = _source_window(root, symbol.file, symbol.line)
            if text:
                snippets.append(
                    {"path": symbol.file, "line": symbol.line, "name": symbol.name, "text": text}
                )
        if not snippets:
            for file in facts.files[:4]:
                text = _source_window(root, file.path, None)
                if text:
                    snippets.append({"path": file.path, "line": None, "name": file.path, "text": text})
        facts.snippets = snippets
        detail = ", ".join(f"{item.name} ({item.file})" for item in facts.symbols[:4])
        if snippets:
            detail = (detail + " · " if detail else "") + f"{len(snippets)} source window(s)"
        detail = detail or "no symbols in this subgraph"
        return {
            "facts": facts,
            "steps": _step(state, "code", "Code retrieval", detail),
        }

    def llm_response(state: AgentState) -> dict:
        intent = state["intent"]
        facts = state["facts"]
        briefing = compose(settings, facts)
        briefing["question"] = state["question"]
        briefing["mode"] = intent["mode"]
        briefing["intent"] = intent["kind"]
        briefing["path"] = store.why_path(state["repo_id"], state["tokens"])
        briefing["citations"] = _citations(facts)
        voice = briefing.get("voice") or "graph"
        model = settings.llm_model if settings.llm_enabled else "graph-only"
        return {
            "briefing": briefing,
            "steps": _step(state, "llm", "LLM response", f"{voice} · {model}"),
        }

    def memory_extraction(state: AgentState) -> dict:
        briefing = dict(state["briefing"])
        writes = extract_memory(state["question"], briefing)
        kinds = ", ".join(sorted({item["kind"] for item in writes})) or "none"
        return {
            "briefing": {**briefing, "memoryWrites": writes},
            "steps": _step(state, "memory", "Memory extraction", kinds),
        }

    def neo4j_updates(state: AgentState) -> dict:
        briefing = dict(state["briefing"])
        facts = state["facts"]
        writes = list(briefing.get("memoryWrites") or [])
        briefing["id"] = store.save_briefing(state["repo_id"], briefing, facts.anchor_ids[:12])
        briefing["createdAt"] = datetime.now(timezone.utc).isoformat()
        applied = ["Conversation stored"]
        applied.extend(apply_memory(store, state["repo_id"], writes, facts.anchor_ids))
        briefing["extracted"] = applied
        steps = _step(state, "write", "Neo4j updates", " · ".join(applied))
        briefing["steps"] = steps
        return {"briefing": briefing, "steps": steps}

    return {
        "intent_classification": intent_classification,
        "graph_retrieval": graph_retrieval,
        "code_retrieval": code_retrieval,
        "llm_response": llm_response,
        "memory_extraction": memory_extraction,
        "neo4j_updates": neo4j_updates,
    }


def _step(state: AgentState, step_id: str, label: str, detail: str) -> list[dict]:
    return list(state.get("steps") or []) + [{"id": step_id, "label": label, "detail": detail}]


def _source_window(root: str, relative: str, line: int | None, radius: int = 20) -> str:
    if not root or not relative:
        return ""
    try:
        text = read_source(root, relative)
    except (FileNotFoundError, PermissionError, OSError):
        return ""
    rows = text.splitlines()
    if not rows:
        return ""
    if not line:
        return "\n".join(rows[:40])[:4000]
    idx = max(int(line) - 1, 0)
    start = max(0, idx - radius)
    end = min(len(rows), idx + radius + 1)
    return "\n".join(rows[start:end])[:4000]


def _citations(facts: BriefingFacts) -> list[dict]:
    rows: list[dict] = []
    for symbol in facts.symbols[:6]:
        rows.append({"kind": symbol.kind, "name": symbol.name, "path": symbol.file, "line": symbol.line})
    for file in facts.files[:6]:
        rows.append({"kind": "file", "name": file.path, "path": file.path, "line": None})
    for issue in facts.issues[:4]:
        rows.append({"kind": "issue", "name": issue.key, "path": issue.title, "line": None})
    for snippet in facts.snippets[:6]:
        rows.append(
            {
                "kind": "snippet",
                "name": snippet.get("name") or snippet.get("path"),
                "path": snippet.get("path") or "",
                "line": snippet.get("line"),
            }
        )
    seen: set[tuple] = set()
    unique: list[dict] = []
    for row in rows:
        key = (row["kind"], row["name"], row["path"], row.get("line"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique


def read_source(root: str, relative: str, limit: int = 80_000) -> str:
    path = Path(root) / relative
    if not path.is_file():
        raise FileNotFoundError(relative)
    resolved = path.resolve()
    base = Path(root).resolve()
    if base not in resolved.parents and resolved != base:
        raise PermissionError("Path is outside the repository")
    return resolved.read_text(encoding="utf-8", errors="replace")[:limit]
