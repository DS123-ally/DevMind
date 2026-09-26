"""Facts extracted from the graph. Narration can only use this object."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SymbolFact:
    kind: str
    name: str
    qualified_name: str
    file: str
    line: int | None = None
    signature: str | None = None
    docstring: str | None = None
    calls: list[str] = field(default_factory=list)
    called_by: list[str] = field(default_factory=list)
    extends: list[str] = field(default_factory=list)


@dataclass
class FileFact:
    path: str
    language: str | None = None
    loc: int | None = None
    docstring: str | None = None
    defines: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    technologies: list[str] = field(default_factory=list)


@dataclass
class DecisionFact:
    title: str
    status: str
    rationale: str
    date: str | None = None
    context: str | None = None
    consequences: str | None = None
    deciders: list[str] = field(default_factory=list)
    supersedes: list[str] = field(default_factory=list)
    about: list[str] = field(default_factory=list)


@dataclass
class IssueFact:
    key: str
    title: str
    status: str
    description: str
    affects: list[str] = field(default_factory=list)
    resolved_by: list[str] = field(default_factory=list)


@dataclass
class ErrorFact:
    type: str
    message: str
    occurs_in: list[str] = field(default_factory=list)
    resolved_by: list[str] = field(default_factory=list)


@dataclass
class PullRequestFact:
    number: int
    title: str
    status: str
    author: str | None = None
    files: list[str] = field(default_factory=list)


@dataclass
class ConversationFact:
    question: str
    headline: str
    created_at: str | None = None


@dataclass
class EvidenceFact:
    source: str
    relationship: str
    target: str
    note: str = ""


@dataclass
class BriefingFacts:
    question: str
    mode: str
    repository: str
    summary: str | None = None
    overview: bool = False
    symbols: list[SymbolFact] = field(default_factory=list)
    files: list[FileFact] = field(default_factory=list)
    technologies: list[str] = field(default_factory=list)
    decisions: list[DecisionFact] = field(default_factory=list)
    issues: list[IssueFact] = field(default_factory=list)
    errors: list[ErrorFact] = field(default_factory=list)
    pull_requests: list[PullRequestFact] = field(default_factory=list)
    conversations: list[ConversationFact] = field(default_factory=list)
    developers: list[str] = field(default_factory=list)
    evidence: list[EvidenceFact] = field(default_factory=list)
    matched: bool = False
    anchor_ids: list[str] = field(default_factory=list)
