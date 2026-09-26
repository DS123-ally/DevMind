"""Question shaping: what vs why, and the tokens used to enter the graph."""

from __future__ import annotations

import re

_WHY = re.compile(
    r"\b(why|reason|rationale|decided|decision|trade-?offs?|instead|history|because|chose|chosen|supersed\w*)\b",
    re.IGNORECASE,
)
_WHAT = re.compile(
    r"\b(what|how|where|which|explain|implement\w*|defined|does|structure|call(?:s|ed|er|ers)?)\b",
    re.IGNORECASE,
)
_TOKEN = re.compile(r"[A-Za-z0-9_./:-]{2,}")
_STOP = {
    "what",
    "why",
    "does",
    "do",
    "did",
    "the",
    "this",
    "that",
    "project",
    "code",
    "work",
    "works",
    "way",
    "how",
    "is",
    "are",
    "was",
    "were",
    "a",
    "an",
    "to",
    "of",
    "in",
    "on",
    "for",
    "and",
    "or",
    "it",
    "we",
    "our",
    "with",
    "from",
    "about",
    "when",
    "where",
    "which",
    "who",
    "whom",
    "into",
    "using",
    "use",
    "used",
    "there",
    "their",
    "its",
    "be",
    "been",
    "being",
    "as",
    "by",
    "at",
    "if",
    "can",
    "could",
    "should",
    "would",
    "please",
    "tell",
    "explain",
    "describe",
    "show",
    "me",
    "you",
    "file",
    "files",
    "function",
    "functions",
    "class",
    "classes",
    "repository",
    "repo",
}

_LUCENE = re.compile(r'([+\-!(){}\[\]^"~*?:\\/]|&&|\|\|)')


def detect_mode(question: str, requested: str | None = None) -> str:
    if requested in {"what", "why", "both"}:
        return requested
    why = bool(_WHY.search(question))
    what = bool(_WHAT.search(question))
    if why and what:
        return "both"
    if why:
        return "why"
    if what:
        return "what"
    return "both"


def tokenize(question: str) -> list[str]:
    tokens: list[str] = []
    seen: set[str] = set()
    for match in _TOKEN.findall(question):
        lowered = match.lower().strip("._-:/")
        if len(lowered) < 2 or lowered in _STOP or lowered in seen:
            continue
        seen.add(lowered)
        tokens.append(lowered)
    return tokens[:10]


def lucene_query(tokens: list[str]) -> str:
    if not tokens:
        return ""
    parts = []
    for token in tokens:
        escaped = _LUCENE.sub(r"\\\1", token)
        parts.append(f"{escaped}*")
    return " OR ".join(parts)
