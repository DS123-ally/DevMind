"""In-memory records produced by a repository scan, before they are written to Neo4j."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DirRec:
    id: str
    path: str
    name: str
    parent_id: str | None


@dataclass
class FileRec:
    id: str
    path: str
    name: str
    language: str
    loc: int
    sha256: str
    directory_id: str
    docstring: str | None = None
    imports: list[str] = field(default_factory=list)
    import_file_ids: list[str] = field(default_factory=list)


@dataclass
class SymbolRec:
    id: str
    kind: str
    name: str
    qualified_name: str
    file_id: str
    file_path: str
    line: int
    signature: str | None = None
    docstring: str | None = None
    class_name: str | None = None
    bases: list[str] = field(default_factory=list)


@dataclass
class TechRec:
    id: str
    name: str
    category: str
    manifest: str
    file_ids: list[str] = field(default_factory=list)


@dataclass
class DecisionRec:
    id: str
    slug: str
    title: str
    status: str
    rationale: str
    source: str
    date: str | None = None
    context: str | None = None
    consequences: str | None = None
    path: str | None = None
    decider_ids: list[str] = field(default_factory=list)
    about_ids: list[str] = field(default_factory=list)
    technology_ids: list[str] = field(default_factory=list)
    informed_by_ids: list[str] = field(default_factory=list)
    supersedes_slug: str | None = None


@dataclass
class IssueRec:
    id: str
    key: str
    title: str
    status: str
    description: str
    source: str
    about_ids: list[str] = field(default_factory=list)
    caused_error_ids: list[str] = field(default_factory=list)
    url: str | None = None
    labels: list[str] = field(default_factory=list)
    assignees: list[str] = field(default_factory=list)
    comments: int = 0
    closed_at: str | None = None


@dataclass
class ErrorRec:
    id: str
    key: str
    type: str
    message: str
    source: str
    about_ids: list[str] = field(default_factory=list)


@dataclass
class SolutionRec:
    id: str
    key: str
    summary: str
    source: str
    resolves_issue_ids: list[str] = field(default_factory=list)
    resolves_error_ids: list[str] = field(default_factory=list)


@dataclass
class PullRequestRec:
    id: str
    number: int
    title: str
    status: str
    source: str
    url: str | None = None
    author_id: str | None = None
    file_ids: list[str] = field(default_factory=list)
    closes_issue_ids: list[str] = field(default_factory=list)
    body: str = ""
    merged: bool = False
    draft: bool = False
    base: str | None = None
    head: str | None = None
    merged_at: str | None = None
    labels: list[str] = field(default_factory=list)


@dataclass
class DeveloperRec:
    id: str
    name: str
    email: str


@dataclass
class IngestDocument:
    repo_id: str
    name: str
    path: str
    summary: str | None
    directories: list[DirRec] = field(default_factory=list)
    files: list[FileRec] = field(default_factory=list)
    symbols: list[SymbolRec] = field(default_factory=list)
    calls: list[tuple[str, str]] = field(default_factory=list)
    extends: list[tuple[str, str]] = field(default_factory=list)
    technologies: list[TechRec] = field(default_factory=list)
    decisions: list[DecisionRec] = field(default_factory=list)
    issues: list[IssueRec] = field(default_factory=list)
    errors: list[ErrorRec] = field(default_factory=list)
    solutions: list[SolutionRec] = field(default_factory=list)
    pull_requests: list[PullRequestRec] = field(default_factory=list)
    developers: list[DeveloperRec] = field(default_factory=list)
    authored: list[tuple[str, str, int]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    memory_loaded: bool = False
    github_url: str | None = None
    default_branch: str | None = None
    languages: dict[str, int] = field(default_factory=dict)
    github: dict[str, object] | None = None
