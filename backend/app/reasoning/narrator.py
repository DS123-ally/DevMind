"""Turn graph facts into a briefing. The wording cannot introduce new project facts."""

from __future__ import annotations

import re

from app.reasoning.facts import BriefingFacts, DecisionFact

_WORD = re.compile(r"[a-z0-9_./:-]{3,}")
_FILLER = {
    "the",
    "and",
    "for",
    "with",
    "this",
    "that",
    "from",
    "into",
    "about",
    "there",
    "their",
    "was",
    "were",
    "are",
    "not",
    "but",
    "its",
    "has",
    "have",
}


def narrate(facts: BriefingFacts) -> dict:
    what = _what(facts)
    why = _why(facts)
    gaps = _gaps(facts, why)
    return {
        "headline": _headline(facts),
        "what": what,
        "why": why,
        "gaps": gaps,
        "evidence": [
            {
                "source": item.source,
                "relationship": item.relationship,
                "target": item.target,
                "note": item.note,
            }
            for item in facts.evidence[:24]
        ],
        "voice": "graph",
    }


def corpus_tokens(facts: BriefingFacts) -> set[str]:
    parts = [
        facts.repository,
        facts.summary or "",
        " ".join(facts.technologies),
        " ".join(facts.developers),
    ]
    for symbol in facts.symbols:
        parts.extend([symbol.name, symbol.qualified_name, symbol.file, symbol.signature or "", symbol.docstring or ""])
        parts.extend(symbol.calls)
        parts.extend(symbol.called_by)
    for file in facts.files:
        parts.extend([file.path, file.docstring or "", " ".join(file.defines), " ".join(file.imports)])
    for decision in facts.decisions:
        parts.extend(
            [
                decision.title,
                decision.rationale,
                decision.context or "",
                decision.consequences or "",
                " ".join(decision.deciders),
                " ".join(decision.supersedes),
                " ".join(decision.about),
            ]
        )
    for issue in facts.issues:
        parts.extend([issue.key, issue.title, issue.description, " ".join(issue.resolved_by)])
    for error in facts.errors:
        parts.extend([error.type, error.message, " ".join(error.resolved_by)])
    for pull in facts.pull_requests:
        parts.extend([str(pull.number), pull.title, pull.author or "", " ".join(pull.files)])
    for item in facts.evidence:
        parts.extend([item.source, item.target, item.note, item.relationship])
    return set(_WORD.findall(" ".join(parts).lower()))


def grounded_bullets(bullets: list[str], corpus: set[str]) -> list[str]:
    kept: list[str] = []
    for bullet in bullets:
        words = [word for word in _WORD.findall(bullet.lower()) if word not in _FILLER]
        if not words:
            continue
        overlap = [word for word in words if word in corpus]
        if len(overlap) >= min(2, len(words)):
            kept.append(bullet.strip())
    return kept


def project_has_reasons(facts: BriefingFacts) -> bool:
    return any(
        [
            facts.decisions,
            facts.issues,
            facts.errors,
            facts.pull_requests,
        ]
    )


def _what(facts: BriefingFacts) -> list[str]:
    lines: list[str] = []
    if facts.overview and facts.summary:
        lines.append(facts.summary)
    for symbol in facts.symbols[:5]:
        where = f"`{symbol.name}` in `{symbol.file}`"
        if symbol.line:
            where += f" line {symbol.line}"
        if symbol.signature:
            where += f" — `{symbol.signature}`"
        if symbol.docstring:
            where += f". {symbol.docstring}"
        lines.append(where + ("" if where.endswith(".") else "."))
        if symbol.calls:
            lines.append(f"`{symbol.name}` calls { _names(symbol.calls) }.")
        if symbol.called_by:
            lines.append(f"`{symbol.name}` is called by { _names(symbol.called_by) }.")
        if symbol.extends:
            lines.append(f"`{symbol.name}` extends { _names(symbol.extends) }.")
    for file in facts.files[:4]:
        if any(symbol.file == file.path for symbol in facts.symbols[:5]):
            continue
        detail = f"`{file.path}`"
        if file.language:
            detail += f" ({file.language})"
        if file.docstring:
            detail += f". {file.docstring}"
        elif file.defines:
            detail += f" defines { _names(file.defines[:8]) }"
        lines.append(detail + ("" if detail.endswith(".") else "."))
    technologies = _technology_names(facts)
    if technologies and (facts.overview or not facts.symbols):
        lines.append("Technologies recorded on this subgraph: " + ", ".join(technologies) + ".")
    if not lines:
        lines.append(f"The graph for {facts.repository} has no symbol or file that answers this.")
    return lines


def _why(facts: BriefingFacts) -> list[str]:
    lines: list[str] = []
    current = [item for item in facts.decisions if item.status not in {"superseded", "rejected"}]
    historical = [item for item in facts.decisions if item.status in {"superseded", "rejected"}]
    for decision in current[:4]:
        lines.append(_decision_line(decision))
    for decision in historical[:2]:
        lines.append(f"Superseded decision “{decision.title}” remains in the graph as history.")
    for issue in facts.issues[:3]:
        line = f"Issue {issue.key} ({issue.status}): {issue.title}."
        if issue.description:
            line += f" {_clip(issue.description, 280)}"
        if issue.resolved_by:
            line += " Resolved by " + "; ".join(_sentence(item) for item in issue.resolved_by) + "."
        lines.append(line)
    for error in facts.errors[:3]:
        line = f"{error.type} recorded on { _names(error.occurs_in) or 'the project' }: {error.message}."
        if error.resolved_by:
            line += " Resolved by " + "; ".join(_sentence(item) for item in error.resolved_by) + "."
        lines.append(line)
    for pull in facts.pull_requests[:3]:
        author = f" by {pull.author}" if pull.author else ""
        files = f" Changes { _names(pull.files) }." if pull.files else ""
        lines.append(f"Pull request #{pull.number} ({pull.status}){author}: {pull.title}.{files}")
    for conversation in facts.conversations[:2]:
        lines.append(f"Earlier briefing: {conversation.headline}")
    if facts.developers and facts.mode in {"why", "both"}:
        lines.append("Developers linked here: " + ", ".join(facts.developers[:6]) + ".")
    return lines


def _gaps(facts: BriefingFacts, why: list[str]) -> list[str]:
    gaps: list[str] = []
    if not facts.matched:
        gaps.append("Nothing in the project graph matches this question. The briefing stays inside what was ingested.")
    if facts.mode in {"why", "both"} and not project_has_reasons(facts):
        gaps.append("No technical decision, issue, error, or pull request in the graph explains this yet.")
    elif facts.mode == "what" and not facts.decisions:
        gaps.append("No technical decision is linked to this part of the project.")
    if facts.matched and not why and facts.mode == "why":
        gaps.append("The matching nodes have no recorded rationale.")
    return _unique(gaps)


def _headline(facts: BriefingFacts) -> str:
    if not facts.matched:
        return "The graph has no match for this question"
    if facts.mode in {"why", "both"}:
        current = [item for item in facts.decisions if item.status not in {"superseded", "rejected"}]
        if current:
            return current[0].title
    if facts.symbols:
        symbol = facts.symbols[0]
        if symbol.docstring:
            sentence = re.split(r"(?<=[.])\s", symbol.docstring)[0]
            if len(sentence) <= 140:
                return sentence.rstrip(".")
        return f"{symbol.name} in {symbol.file}"
    if facts.summary:
        return _clip(facts.summary.split(". ")[0], 140)
    return facts.repository


def _decision_line(decision: DecisionFact) -> str:
    who = f", {', '.join(decision.deciders)}" if decision.deciders else ""
    when = f", {decision.date}" if decision.date else ""
    about = f" About { _names(decision.about) }." if decision.about else ""
    supersedes = f" It supersedes { _names(decision.supersedes) }." if decision.supersedes else ""
    body = _clip(decision.rationale, 420)
    context = f" Context: {_clip(decision.context, 220)}" if decision.context else ""
    consequences = f" Consequences: {_clip(decision.consequences, 220)}" if decision.consequences else ""
    return (
        f"Decision “{decision.title}” ({decision.status}{when}{who}).{about} {body}{supersedes}{context}{consequences}"
    ).strip()


def _technology_names(facts: BriefingFacts) -> list[str]:
    names = list(facts.technologies)
    for file in facts.files:
        names.extend(file.technologies)
    return _unique(names)


def _names(items: list[str]) -> str:
    cleaned = [f"`{item}`" if item and not item.startswith("`") else item for item in items if item]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    if len(cleaned) == 2:
        return f"{cleaned[0]} and {cleaned[1]}"
    return ", ".join(cleaned[:-1]) + f", and {cleaned[-1]}"


def _sentence(text: str) -> str:
    return text.strip().rstrip(".")


def _clip(text: str, limit: int) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "…"


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered
