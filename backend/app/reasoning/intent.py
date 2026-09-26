"""Classify a question so the graph walk matches the job: callers, bugs, technologies, why."""

from __future__ import annotations

import re

from app.reasoning.query import detect_mode, tokenize

_USED = re.compile(r"\b(where.{0,20}used|callers?|who calls|used by)\b", re.I)
_TECH = re.compile(r"(technolog|framework|libraries|stack|\bredis\b|why.{0,20}using)", re.I)
_BUG = re.compile(r"\b(bug|error|seen this|integrityerror|exception|failed before)\b", re.I)
_FIXED = re.compile(r"\b(how.{0,16}fix|resolved|solution|fixed)\b", re.I)
_CAUSED = re.compile(r"\b(what caused|root cause|why did .{0,20}fail)\b", re.I)
_AUTH = re.compile(r"\b(auth|login|session|oauth|jwt)\b", re.I)
_FILES = re.compile(r"\b(which files|what files|handle)\b", re.I)


def detect_intent(question: str, requested_mode: str | None = None) -> dict:
    mode = detect_mode(question, requested_mode)
    kind = "overview"
    if _USED.search(question):
        kind = "callers"
        mode = "what"
    elif _FIXED.search(question):
        kind = "how_fixed"
        mode = "why"
    elif _CAUSED.search(question) or (_BUG.search(question) and "why" in question.lower()):
        kind = "caused"
        mode = "why"
    elif _BUG.search(question):
        kind = "seen_bug"
        mode = "why"
    elif _TECH.search(question):
        kind = "technologies"
        if "why" in question.lower() or "using" in question.lower():
            kind = "why_technology"
            mode = "why"
        else:
            mode = "what"
    elif _FILES.search(question) or _AUTH.search(question):
        kind = "files_for_topic"
        mode = mode if requested_mode else "what"
    elif tokenize(question):
        kind = "symbol" if mode == "what" else "why_topic"
    return {"kind": kind, "mode": mode, "tokens": tokenize(question), "question": question}
