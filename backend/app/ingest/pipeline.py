"""Walk a repository and build the document Neo4j will remember."""

from __future__ import annotations

import posixpath
from pathlib import Path

from app.ids import node_id, person_key, repo_id_for
from app.ingest.gitlog import collect_authorship
from app.ingest.memory_file import load_memory
from app.ingest.model import (
    DecisionRec,
    DeveloperRec,
    DirRec,
    ErrorRec,
    FileRec,
    IngestDocument,
    IssueRec,
    PullRequestRec,
    SolutionRec,
    SymbolRec,
    TechRec,
)
from app.ingest.parsers import is_adr_path, parse_adr, parse_source, readme_summary
from app.ingest.resolve import resolve_targets
from app.ingest.scanner import MAX_FILES, ExtractedFile, extract_repository
from app.ingest.technologies import (
    category_for,
    import_matches_technology,
    normalize_package,
    technologies_in_manifest,
)

_SKIP_BASES = {"object", "exception", "baseexception", "abc", "enum"}


class IngestLimitError(ValueError):
    """Raised when a path is too large to ingest safely."""


def scan(
    root: Path,
    name: str | None = None,
    github_url: str | None = None,
    github_token: str = "",
) -> IngestDocument:
    root = root.resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"{root} is not a directory")

    repo_id = repo_id_for(root)
    extracted = extract_repository(root)
    if len(extracted) > MAX_FILES:
        raise IngestLimitError(
            f"Refusing to ingest {len(extracted)} files (limit {MAX_FILES}). Choose a project directory."
        )

    doc = IngestDocument(
        repo_id=repo_id,
        name=name or root.name,
        path=str(root),
        summary=None,
    )
    directories: dict[str, DirRec] = {}
    files_by_path: dict[str, str] = {}
    parsed_calls: dict[str, list[str]] = {}
    symbols_by_name: dict[str, list[tuple[str, str]]] = {}
    classes_by_name: dict[str, list[SymbolRec]] = {}
    developers: dict[str, DeveloperRec] = {}

    for item in extracted:
        rel = item.rel
        directory_id = _ensure_directories(repo_id, rel, directories)
        module = parse_source(rel, item.text) if item.readable else None
        file_id = node_id(repo_id, "file", rel)
        files_by_path[rel] = file_id
        doc.files.append(
            FileRec(
                id=file_id,
                path=rel,
                name=item.path.name,
                language=item.language,
                loc=item.loc,
                sha256=item.sha256,
                directory_id=directory_id,
                docstring=module.docstring if module else None,
                imports=list(module.imports) if module else [],
            )
        )
        if module is None:
            continue
        for parsed in module.classes:
            symbol = SymbolRec(
                id=node_id(repo_id, "class", f"{rel}::{parsed.name}"),
                kind="class",
                name=parsed.name,
                qualified_name=f"{rel}::{parsed.name}",
                file_id=file_id,
                file_path=rel,
                line=parsed.line,
                docstring=parsed.docstring,
                bases=parsed.bases,
            )
            doc.symbols.append(symbol)
            classes_by_name.setdefault(parsed.name, []).append(symbol)
            symbols_by_name.setdefault(parsed.name, []).append((symbol.id, rel))
        for parsed in module.functions:
            qual = f"{rel}::{parsed.class_name}.{parsed.name}" if parsed.class_name else f"{rel}::{parsed.name}"
            symbol = SymbolRec(
                id=node_id(repo_id, "function", qual),
                kind="method" if parsed.class_name else "function",
                name=parsed.name,
                qualified_name=qual,
                file_id=file_id,
                file_path=rel,
                line=parsed.line,
                signature=parsed.signature,
                docstring=parsed.docstring,
                class_name=parsed.class_name,
            )
            doc.symbols.append(symbol)
            parsed_calls[symbol.id] = parsed.calls
            symbols_by_name.setdefault(parsed.name, []).append((symbol.id, rel))

    doc.directories = list(directories.values())
    _link_imports(doc, files_by_path)
    _link_calls(doc, parsed_calls)
    _link_extends(doc, classes_by_name)
    _collect_technologies(doc, extracted, files_by_path)
    _collect_developers(doc, root, developers)
    _collect_adrs(doc, extracted, files_by_path, symbols_by_name, developers)
    _collect_memory(doc, root, files_by_path, symbols_by_name, developers)
    if not github_url and (root / ".git").exists():
        from app.ingest.github import github_url_from_git

        github_url = github_url_from_git(root)
    if github_url:
        from app.ingest.github import fetch_github_memory

        try:
            fetch_github_memory(github_url, github_token, doc, files_by_path, symbols_by_name, developers)
        except Exception as exc:
            doc.warnings.append(f"GitHub metadata was not imported ({exc}).")
    _link_supersedes(doc)
    _link_decision_technologies(doc)
    readme = root / "README.md"
    if readme.is_file() and not doc.summary:
        doc.summary = readme_summary(readme.read_text(encoding="utf-8", errors="replace"))
    elif readme.is_file() and not github_url:
        doc.summary = readme_summary(readme.read_text(encoding="utf-8", errors="replace")) or doc.summary
    counts: dict[str, int] = {}
    for file in doc.files:
        if file.language and file.language != "text":
            counts[file.language] = counts.get(file.language, 0) + 1
    doc.languages = counts
    doc.developers = list(developers.values())
    return doc


def _ensure_directories(repo_id: str, rel: str, directories: dict[str, DirRec]) -> str:
    parent = posixpath.dirname(rel)
    chain: list[str] = []
    cursor = parent
    while cursor and cursor not in directories:
        chain.append(cursor)
        next_parent = posixpath.dirname(cursor)
        if next_parent == cursor:
            break
        cursor = next_parent
    if "." not in directories:
        directories["."] = DirRec(id=node_id(repo_id, "directory", "."), path=".", name="", parent_id=None)
    for directory in reversed(chain):
        parent_path = posixpath.dirname(directory) or "."
        if parent_path == directory:
            parent_path = "."
        directories[directory] = DirRec(
            id=node_id(repo_id, "directory", directory),
            path=directory,
            name=posixpath.basename(directory),
            parent_id=directories[parent_path].id if parent_path in directories else node_id(repo_id, "directory", "."),
        )
    return directories[parent or "."].id


def _link_imports(doc: IngestDocument, files_by_path: dict[str, str]) -> None:
    for file in doc.files:
        resolved: list[str] = []
        for module in file.imports:
            target = _resolve_module(file.path, module, files_by_path)
            if target and target != file.id:
                resolved.append(target)
        file.import_file_ids = list(dict.fromkeys(resolved))


def _resolve_module(importer: str, module: str, files_by_path: dict[str, str]) -> str | None:
    if module.startswith("."):
        base = posixpath.dirname(importer)
        level = len(module) - len(module.lstrip("."))
        spec = module.lstrip(".")
        for _ in range(max(level - 1, 0)):
            base = posixpath.dirname(base)
        target = posixpath.normpath(posixpath.join(base, spec)) if spec else base
    else:
        target = "/".join(module.split("."))
    for candidate in (
        target,
        f"{target}.py",
        f"{target}.ts",
        f"{target}.tsx",
        f"{target}.js",
        f"{target}.jsx",
        f"{target}/__init__.py",
        f"{target}/index.ts",
        f"{target}/index.js",
    ):
        if candidate in files_by_path:
            return files_by_path[candidate]
    return None


def _link_calls(doc: IngestDocument, parsed_calls: dict[str, list[str]]) -> None:
    functions = [symbol for symbol in doc.symbols if symbol.kind in {"function", "method"}]
    by_name: dict[str, list[SymbolRec]] = {}
    for symbol in functions:
        by_name.setdefault(symbol.name, []).append(symbol)
    edges: set[tuple[str, str]] = set()
    for symbol in functions:
        for callee in parsed_calls.get(symbol.id, []):
            matches = by_name.get(callee, [])
            same_file = [item for item in matches if item.file_id == symbol.file_id]
            chosen = same_file if len(same_file) == 1 else (matches if len(matches) == 1 else [])
            if len(chosen) == 1 and chosen[0].id != symbol.id:
                edges.add((symbol.id, chosen[0].id))
    doc.calls = sorted(edges)


def _link_extends(doc: IngestDocument, classes_by_name: dict[str, list[SymbolRec]]) -> None:
    edges: set[tuple[str, str]] = set()
    for symbol in doc.symbols:
        if symbol.kind != "class":
            continue
        for base in symbol.bases:
            if base.lower() in _SKIP_BASES:
                continue
            matches = classes_by_name.get(base, [])
            same_file = [item for item in matches if item.file_id == symbol.file_id]
            chosen = same_file if len(same_file) == 1 else (matches if len(matches) == 1 else [])
            if len(chosen) == 1 and chosen[0].id != symbol.id:
                edges.add((symbol.id, chosen[0].id))
    doc.extends = sorted(edges)


def _collect_technologies(
    doc: IngestDocument,
    extracted: list[ExtractedFile],
    files_by_path: dict[str, str],
) -> None:
    techs: dict[str, TechRec] = {}
    for item in extracted:
        packages = technologies_in_manifest(item.rel, item.text)
        if not packages:
            continue
        for package, manifest in packages:
            key = normalize_package(package)
            record = techs.get(key)
            if record is None:
                record = TechRec(
                    id=node_id(doc.repo_id, "technology", key),
                    name=key,
                    category=category_for(package),
                    manifest=manifest,
                )
                techs[key] = record
            file_id = files_by_path.get(manifest)
            if file_id and file_id not in record.file_ids:
                record.file_ids.append(file_id)

    known = set(techs)
    for file in doc.files:
        for module in file.imports:
            matched = import_matches_technology(module, known)
            if matched and file.id not in techs[matched].file_ids:
                techs[matched].file_ids.append(file.id)
    doc.technologies = list(techs.values())


def _collect_developers(doc: IngestDocument, root: Path, developers: dict[str, DeveloperRec]) -> None:
    authorship = collect_authorship(root)
    files = {file.path: file.id for file in doc.files}
    for path, people in authorship.items():
        file_id = files.get(path)
        if not file_id:
            continue
        for email, info in people.items():
            dev_id = _developer(developers, doc.repo_id, str(info["name"]), email)
            doc.authored.append((dev_id, file_id, int(info["count"])))


def _collect_adrs(
    doc: IngestDocument,
    extracted: list[ExtractedFile],
    files_by_path: dict[str, str],
    symbols_by_name: dict[str, list[tuple[str, str]]],
    developers: dict[str, DeveloperRec],
) -> None:
    for item in extracted:
        rel = item.rel
        if not is_adr_path(rel):
            continue
        parsed = parse_adr(rel, item.text)
        if parsed is None:
            continue
        slug = item.path.stem
        decider_ids = [_developer_by_name(developers, doc.repo_id, name) for name in parsed.deciders]
        about = resolve_targets(parsed.affects, files_by_path, symbols_by_name)
        file_id = files_by_path.get(rel)
        if file_id and file_id not in about:
            about.append(file_id)
        doc.decisions.append(
            DecisionRec(
                id=node_id(doc.repo_id, "decision", slug),
                slug=slug,
                title=parsed.title,
                status=parsed.status,
                rationale=parsed.decision or parsed.title,
                source="adr",
                date=parsed.date,
                context=parsed.context,
                consequences=parsed.consequences,
                path=rel,
                decider_ids=decider_ids,
                about_ids=about,
                supersedes_slug=parsed.supersedes,
            )
        )


def _collect_memory(
    doc: IngestDocument,
    root: Path,
    files_by_path: dict[str, str],
    symbols_by_name: dict[str, list[tuple[str, str]]],
    developers: dict[str, DeveloperRec],
) -> None:
    memory_path = root / ".devmind" / "memory.json"
    if not memory_path.is_file():
        return
    bundle = load_memory(memory_path.read_text(encoding="utf-8", errors="replace"))
    doc.memory_loaded = True
    doc.warnings.extend(bundle.warnings)
    issue_ids: dict[str, str] = {}
    error_ids: dict[str, str] = {}
    pending_causes: list[tuple[str, list[str]]] = []
    solution_ids: dict[str, str] = {}

    for item in bundle.issues:
        key = str(item.get("key") or item.get("title") or "").strip()
        title = str(item.get("title") or "").strip()
        if not key or not title:
            doc.warnings.append("Skipped an issue missing key or title.")
            continue
        issue_id = node_id(doc.repo_id, "issue", key)
        issue_ids[key] = issue_id
        doc.issues.append(
            IssueRec(
                id=issue_id,
                key=key,
                title=title,
                status=str(item.get("status") or "open"),
                description=str(item.get("description") or ""),
                source="memory",
                about_ids=resolve_targets(_string_list(item.get("affects")), files_by_path, symbols_by_name),
                caused_error_ids=[],
            )
        )
        pending_causes.append((issue_id, _string_list(item.get("caused") or item.get("errors"))))

    for item in bundle.errors:
        key = str(item.get("key") or item.get("message") or "").strip()
        message = str(item.get("message") or "").strip()
        if not key or not message:
            doc.warnings.append("Skipped an error missing key or message.")
            continue
        error_id = node_id(doc.repo_id, "error", key)
        error_ids[key] = error_id
        doc.errors.append(
            ErrorRec(
                id=error_id,
                key=key,
                type=str(item.get("type") or "Error"),
                message=message,
                source="memory",
                about_ids=resolve_targets(_string_list(item.get("occursIn")), files_by_path, symbols_by_name),
            )
        )

    for issue_id, keys in pending_causes:
        for issue in doc.issues:
            if issue.id != issue_id:
                continue
            issue.caused_error_ids = [error_ids[key] for key in keys if key in error_ids]
            break

    for item in bundle.solutions:
        key = str(item.get("key") or item.get("summary") or "").strip()
        summary = str(item.get("summary") or "").strip()
        if not key or not summary:
            doc.warnings.append("Skipped a solution missing key or summary.")
            continue
        resolves = [str(part) for part in _string_list(item.get("resolves"))]
        solution_id = node_id(doc.repo_id, "solution", key)
        solution_ids[key] = solution_id
        doc.solutions.append(
            SolutionRec(
                id=solution_id,
                key=key,
                summary=summary,
                source="memory",
                resolves_issue_ids=[issue_ids[part] for part in resolves if part in issue_ids],
                resolves_error_ids=[error_ids[part] for part in resolves if part in error_ids],
            )
        )

    for item in bundle.pull_requests:
        number = item.get("number")
        title = str(item.get("title") or "").strip()
        if not isinstance(number, int) or not title:
            doc.warnings.append("Skipped a pull request missing number or title.")
            continue
        author = str(item.get("author") or "").strip()
        email = str(item.get("authorEmail") or "").strip()
        author_id = None
        if author or email:
            author_id = _developer(developers, doc.repo_id, author or email, email or None)
        doc.pull_requests.append(
            PullRequestRec(
                id=node_id(doc.repo_id, "pullrequest", str(number)),
                number=number,
                title=title,
                status=str(item.get("status") or "open"),
                source="memory",
                url=str(item.get("url") or "") or None,
                author_id=author_id,
                file_ids=resolve_targets(_string_list(item.get("changes")), files_by_path, symbols_by_name),
                closes_issue_ids=[issue_ids[part] for part in _string_list(item.get("closes")) if part in issue_ids],
            )
        )

    for item in bundle.decisions:
        title = str(item.get("title") or "").strip()
        rationale = str(item.get("rationale") or "").strip()
        if not title or not rationale:
            doc.warnings.append("Skipped a memory decision missing title or rationale.")
            continue
        slug = str(item.get("slug") or _slug(title))
        names = _string_list(item.get("deciders"))
        doc.decisions.append(
            DecisionRec(
                id=node_id(doc.repo_id, "decision", slug),
                slug=slug,
                title=title,
                status=str(item.get("status") or "accepted").lower(),
                rationale=rationale,
                source="memory",
                date=str(item.get("date") or "") or None,
                decider_ids=[_developer_by_name(developers, doc.repo_id, name) for name in names],
                about_ids=resolve_targets(_string_list(item.get("affects")), files_by_path, symbols_by_name),
                informed_by_ids=[solution_ids[part] for part in _string_list(item.get("informedBy")) if part in solution_ids],
                supersedes_slug=str(item.get("supersedes") or "") or None,
            )
        )


def _link_supersedes(doc: IngestDocument) -> None:
    by_slug = {decision.slug.lower(): decision for decision in doc.decisions}
    by_title = {decision.title.lower(): decision for decision in doc.decisions}
    for decision in doc.decisions:
        token = (decision.supersedes_slug or "").strip().lower()
        if not token:
            continue
        match = by_slug.get(token) or by_title.get(token)
        if match is None:
            for slug, candidate in by_slug.items():
                if slug.endswith(token) or token.endswith(slug):
                    match = candidate
                    break
        decision.supersedes_slug = match.slug if match and match.id != decision.id else None


def _link_decision_technologies(doc: IngestDocument) -> None:
    techs = {item.name.lower(): item.id for item in doc.technologies}
    for decision in doc.decisions:
        blob = " ".join(
            part for part in [decision.title, decision.rationale, decision.context or "", decision.path or ""] if part
        ).lower()
        for name, tech_id in techs.items():
            if len(name) >= 3 and name in blob and tech_id not in decision.technology_ids:
                decision.technology_ids.append(tech_id)
    issue_to_solutions: dict[str, list[str]] = {}
    for solution in doc.solutions:
        for issue_id in solution.resolves_issue_ids:
            issue_to_solutions.setdefault(issue_id, []).append(solution.id)
    issues = {item.id: item for item in doc.issues}
    for decision in doc.decisions:
        if decision.informed_by_ids:
            continue
        about = set(decision.about_ids)
        for issue in issues.values():
            if about & set(issue.about_ids):
                decision.informed_by_ids.extend(issue_to_solutions.get(issue.id, []))



def _developer(developers: dict[str, DeveloperRec], repo_id: str, name: str, email: str | None) -> str:
    key = person_key(name, email)
    dev_id = node_id(repo_id, "developer", key)
    if dev_id not in developers:
        developers[dev_id] = DeveloperRec(id=dev_id, name=name.strip() or key, email=(email or "").strip().lower())
    return dev_id


def _developer_by_name(developers: dict[str, DeveloperRec], repo_id: str, name: str) -> str:
    folded = name.strip().casefold()
    for developer in developers.values():
        if developer.name.casefold() == folded:
            return developer.id
    return _developer(developers, repo_id, name, None)


def _string_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _slug(title: str) -> str:
    cleaned = "".join(char.lower() if char.isalnum() else "-" for char in title)
    return "-".join(part for part in cleaned.split("-") if part)[:80]
