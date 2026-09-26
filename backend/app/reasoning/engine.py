"""Build a briefing by walking the project graph, then store that briefing as a Conversation."""

from __future__ import annotations

from datetime import datetime, timezone

from app.config import Settings
from app.reasoning.facts import (
    BriefingFacts,
    ConversationFact,
    DecisionFact,
    ErrorFact,
    EvidenceFact,
    FileFact,
    IssueFact,
    PullRequestFact,
    SymbolFact,
)
from app.reasoning.llm import compose
from app.reasoning.query import detect_mode, lucene_query, tokenize


def ask(store, settings: Settings, repo_id: str, question: str, requested_mode: str | None) -> dict:
    mode = detect_mode(question, requested_mode)
    tokens = tokenize(question)
    if not store.get_project(repo_id):
        raise LookupError("Repository not found")

    if not tokens:
        graph = store.overview(repo_id)
        facts = _from_overview(question, mode, repo_id, graph, matched=True)
    else:
        seeds = [seed for seed in store.search(repo_id, tokens, lucene_query(tokens)) if seed["label"] != "Repository"]
        if not seeds:
            graph = store.overview(repo_id)
            facts = _from_overview(question, mode, repo_id, graph, matched=False)
        else:
            seed_ids = [seed["id"] for seed in seeds[:8]]
            graph = store.neighborhood(repo_id, seed_ids)
            facts = _from_neighborhood(question, mode, graph, seed_ids)

    briefing = compose(settings, facts)
    briefing["question"] = question
    briefing["mode"] = mode
    briefing["id"] = store.save_briefing(repo_id, briefing, facts.anchor_ids[:12])
    briefing["createdAt"] = datetime.now(timezone.utc).isoformat()
    return briefing


def _from_overview(question: str, mode: str, repo_id: str, graph: dict, matched: bool) -> BriefingFacts:
    repository = graph.get("repository") or {}
    facts = BriefingFacts(
        question=question,
        mode=mode,
        repository=repository.get("name") or "repository",
        summary=repository.get("summary"),
        overview=True,
        matched=matched,
        anchor_ids=[repo_id],
    )
    facts.technologies = [
        _tech_label(item.get("name"), item.get("category"))
        for item in graph.get("technologies") or []
        if item.get("name")
    ]
    facts.decisions = [_decision(row, facts.repository) for row in graph.get("decisions") or []]
    facts.files = [_overview_file(row) for row in graph.get("files") or [] if row.get("file")]
    facts.conversations = [_conversation(row) for row in graph.get("conversations") or [] if row.get("headline")]
    facts.developers = _unique(name for decision in facts.decisions for name in decision.deciders)
    for decision in facts.decisions:
        for target in decision.about[:3]:
            facts.evidence.append(EvidenceFact(decision.title, "ABOUT", target))
    for technology in facts.technologies:
        facts.evidence.append(EvidenceFact(facts.repository, "USES", technology))
    return facts


def _from_neighborhood(question: str, mode: str, graph: dict, seed_ids: list[str]) -> BriefingFacts:
    repository = graph.get("repository") or {}
    repo_name = repository.get("name") or "repository"
    facts = BriefingFacts(
        question=question,
        mode=mode,
        repository=repo_name,
        summary=repository.get("summary"),
        matched=True,
    )
    nodes = graph.get("nodes") or []
    by_id = {node["id"]: node for node in nodes}
    seed_set = set(seed_ids)

    symbol_nodes = [node for node in nodes if _label(node) in {"Function", "Class"}]
    symbol_nodes.sort(key=lambda node: (node["id"] not in seed_set, node["props"].get("filePath") or ""))
    selected = symbol_nodes[:6]
    selected_ids = {node["id"] for node in selected}

    calls_out: dict[str, list[str]] = {}
    calls_in: dict[str, list[str]] = {}
    for edge in graph.get("calls") or []:
            if edge["fromId"] in selected_ids or edge["toId"] in selected_ids:
                calls_out.setdefault(edge["fromId"], []).append(_short(edge["toName"]))
                calls_in.setdefault(edge["toId"], []).append(_short(edge["fromName"]))
            if edge["fromId"] in selected_ids:
                facts.evidence.append(
                    EvidenceFact(_short(edge["fromName"]), "CALLS", _short(edge["toName"]), edge["fromName"])
                )

    extends = {node["id"]: [] for node in selected}
    for edge in graph.get("extends") or []:
        for node in selected:
            if node["props"].get("name") == edge["fromName"]:
                extends[node["id"]].append(edge["toName"])
                facts.evidence.append(EvidenceFact(edge["fromName"], "EXTENDS", edge["toName"]))

    for node in selected:
        props = node["props"]
        facts.symbols.append(
            SymbolFact(
                kind=_label(node).lower(),
                name=props.get("name") or "",
                qualified_name=props.get("qualifiedName") or props.get("name") or "",
                file=props.get("filePath") or "",
                line=props.get("line"),
                signature=props.get("signature"),
                docstring=props.get("docstring"),
                calls=_unique(calls_out.get(node["id"], [])),
                called_by=_unique(calls_in.get(node["id"], [])),
                extends=extends.get(node["id"], []),
            )
        )
        facts.anchor_ids.append(node["id"])

    file_nodes = [node for node in nodes if _label(node) == "File"]
    file_nodes.sort(key=lambda node: (node["id"] not in seed_set, node["props"].get("path") or ""))
    wanted_paths = {symbol.file for symbol in facts.symbols}
    chosen_files = []
    for node in file_nodes:
        path = node["props"].get("path")
        if node["id"] in seed_set or path in wanted_paths or _label(by_id.get(node["id"], node)) == "File":
            chosen_files.append(node)
    if not facts.symbols:
        chosen_files = file_nodes[:4]
    else:
        chosen_files = [node for node in chosen_files if node["props"].get("path") in wanted_paths or node["id"] in seed_set][:4]

    uses: dict[str, list[str]] = {}
    for edge in graph.get("uses") or []:
        uses.setdefault(edge["owner"], []).append(edge["technology"])
    imports: dict[str, list[str]] = {}
    for edge in graph.get("imports") or []:
        imports.setdefault(edge["fromPath"], []).append(edge["toPath"])
        facts.evidence.append(EvidenceFact(edge["fromPath"], "IMPORTS", edge["toPath"]))

    defined: dict[str, list[str]] = {}
    for node in symbol_nodes:
        defined.setdefault(node["props"].get("filePath") or "", []).append(node["props"].get("name") or "")

    for node in chosen_files[:4]:
        props = node["props"]
        path = props.get("path") or ""
        facts.files.append(
            FileFact(
                path=path,
                language=props.get("language"),
                loc=props.get("loc"),
                docstring=props.get("docstring"),
                defines=_unique(defined.get(path, []))[:8],
                imports=imports.get(path, [])[:8],
                technologies=_unique(uses.get(path, [])),
            )
        )
        facts.anchor_ids.append(node["id"])
        for technology in uses.get(path, []):
            facts.evidence.append(EvidenceFact(path, "USES", technology))

    tech_nodes = [node for node in nodes if _label(node) == "Technology"]
    facts.technologies = _unique(
        [node["props"].get("name") for node in tech_nodes if node["props"].get("name")]
        + [name for names in uses.values() for name in names]
    )
    for node in tech_nodes:
        if node["id"] in seed_set:
            facts.anchor_ids.append(node["id"])

    facts.decisions = [_decision(row, repo_name) for row in graph.get("decisions") or []]
    for row, decision in zip(graph.get("decisions") or [], facts.decisions, strict=False):
        decision_id = (row.get("decision") or {}).get("id")
        if decision_id:
            facts.anchor_ids.append(decision_id)
        for target in decision.about[:4]:
            facts.evidence.append(EvidenceFact(decision.title, "ABOUT", target))
        for previous in decision.supersedes:
            facts.evidence.append(EvidenceFact(decision.title, "SUPERSEDES", previous))
        for person in decision.deciders:
            facts.evidence.append(EvidenceFact(person, "DECIDED", decision.title))

    for row in graph.get("issues") or []:
        issue = _issue(row, repo_name)
        if issue:
            facts.issues.append(issue)
            issue_id = (row.get("issue") or {}).get("id")
            if issue_id:
                facts.anchor_ids.append(issue_id)
            for solution in issue.resolved_by:
                facts.evidence.append(EvidenceFact(solution, "RESOLVES", issue.key))

    for row in graph.get("errors") or []:
        error = _error(row, repo_name)
        if error:
            facts.errors.append(error)
            for solution in error.resolved_by:
                facts.evidence.append(EvidenceFact(solution, "RESOLVES", error.type))

    for row in graph.get("pullRequests") or []:
        pull = _pull(row)
        if pull:
            facts.pull_requests.append(pull)
            for path in pull.files[:4]:
                facts.evidence.append(EvidenceFact(f"PR #{pull.number}", "CHANGES", path))

    facts.conversations = [_conversation(row) for row in graph.get("conversations") or [] if row.get("headline")]
    author_lines = []
    for row in graph.get("developers") or []:
        if row.get("name") and row.get("path"):
            commits = row.get("commits") or 0
            author_lines.append(f"{row['name']} ({commits} commits on {row['path']})")
            facts.evidence.append(EvidenceFact(row["name"], "AUTHORED", row["path"], f"{commits} commits"))
    facts.developers = _unique(author_lines + [name for decision in facts.decisions for name in decision.deciders])
    facts.anchor_ids = _unique(facts.anchor_ids)[:12]
    facts.evidence = _unique_evidence(facts.evidence)[:24]
    return facts


def _decision(row: dict, repo_name: str) -> DecisionFact:
    props = row.get("decision") or {}
    return DecisionFact(
        title=props.get("title") or "Untitled decision",
        status=(props.get("status") or "accepted").lower(),
        rationale=props.get("rationale") or "",
        date=props.get("date"),
        context=props.get("context"),
        consequences=props.get("consequences"),
        deciders=_clean(row.get("deciders")),
        supersedes=_clean(row.get("supersedes")),
        about=_focus_about(_clean(row.get("about")), repo_name),
    )


def _issue(row: dict, repo_name: str) -> IssueFact | None:
    props = row.get("issue") or {}
    if not props.get("title"):
        return None
    return IssueFact(
        key=props.get("key") or props.get("title"),
        title=props["title"],
        status=props.get("status") or "open",
        description=props.get("description") or "",
        affects=[item for item in _clean(row.get("affects")) if item != repo_name],
        resolved_by=_clean(row.get("solutions")),
    )


def _error(row: dict, repo_name: str) -> ErrorFact | None:
    props = row.get("error") or {}
    if not props.get("message"):
        return None
    return ErrorFact(
        type=props.get("type") or "Error",
        message=props["message"],
        occurs_in=[item for item in _clean(row.get("occursIn")) if item != repo_name],
        resolved_by=_clean(row.get("solutions")),
    )


def _pull(row: dict) -> PullRequestFact | None:
    props = row.get("pullRequest") or {}
    if not props.get("title"):
        return None
    authors = _clean(row.get("authors"))
    return PullRequestFact(
        number=int(props.get("number") or 0),
        title=props["title"],
        status=props.get("status") or "open",
        author=authors[0] if authors else None,
        files=_clean(row.get("files")),
    )


def _focus_about(about: list[str], repo_name: str) -> list[str]:
    covered = {item.split("::")[0] for item in about if "::" in item}
    focused = []
    for item in about:
        if item in {repo_name, "."} or item in covered:
            continue
        focused.append(item)
    return focused


def _overview_file(row: dict) -> FileFact:
    props = row.get("file") or {}
    return FileFact(
        path=props.get("path") or "",
        language=props.get("language"),
        loc=props.get("loc"),
        docstring=props.get("docstring"),
        defines=_clean(row.get("defines")),
    )


def _conversation(row: dict) -> ConversationFact:
    return ConversationFact(
        question=row.get("question") or "",
        headline=row.get("headline") or "",
        created_at=row.get("createdAt"),
    )


def _tech_label(name: str | None, category: str | None) -> str:
    if category and category != "library":
        return f"{name} ({category})"
    return name or ""


def _label(node: dict) -> str:
    labels = node.get("labels") or []
    return labels[0] if labels else "Node"


def _short(qualified: str) -> str:
    tail = (qualified or "").split("::")[-1]
    return tail.split(".")[-1] or qualified


def _clean(values) -> list[str]:
    if not values:
        return []
    cleaned = []
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text and text.lower() != "none":
            cleaned.append(text)
    return _unique(cleaned)


def _unique(items) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def _unique_evidence(items: list[EvidenceFact]) -> list[EvidenceFact]:
    seen: set[tuple[str, str, str]] = set()
    ordered: list[EvidenceFact] = []
    for item in items:
        key = (item.source, item.relationship, item.target)
        if key in seen:
            continue
        seen.add(key)
        ordered.append(item)
    return ordered
