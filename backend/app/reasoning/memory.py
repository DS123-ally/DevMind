"""Turn explicit user statements into Neo4j memory writes. Nothing is invented."""

from __future__ import annotations

import re

_TICKET = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")
_DECISION = re.compile(
    r"(?:remember(?:\s+that)?|record\s+that|we decided(?:\s+to)?|decision:)\s+(.+)",
    re.I | re.S,
)
_RESOLVE = re.compile(
    r"(?:resolved|fixed)\s+([A-Z][A-Z0-9]+-\d+)\s+(?:by|with|:)\s+(.+)",
    re.I | re.S,
)
_SOLUTION = re.compile(
    r"(?:the fix was|we (?:fixed|resolved)(?:\s+it)?(?:\s+by)?|solution:)\s+(.+)",
    re.I | re.S,
)
_ISSUE = re.compile(
    r"(?:issue|ticket|bug)\s+([A-Z][A-Z0-9]+-\d+)\s*[:\-–]?\s*(.+)?",
    re.I,
)
_ISSUE_FILE = re.compile(
    r"(?:file[d]?(?:\s+an?)?\s+issue|log(?:ged)? (?:a )?bug)\s*[:\-]\s*(.+)",
    re.I,
)


def extract_memory(question: str, briefing: dict) -> list[dict]:
    text = " ".join(question.split()).strip()
    writes: list[dict] = []
    if not text:
        return writes

    decision = _DECISION.search(text)
    if decision:
        body = re.sub(r"^(?:we decided(?:\s+to)?)\s+", "", decision.group(1).strip(), flags=re.I)
        title, rationale = _split_because(body)
        writes.append({"kind": "decision", "title": title, "rationale": rationale})

    resolved = _RESOLVE.search(text)
    if resolved:
        key = resolved.group(1).upper()
        summary = resolved.group(2).strip().rstrip(".")[:4000]
        writes.append(
            {
                "kind": "issue",
                "key": key,
                "title": briefing.get("headline") or f"Issue {key}",
                "description": summary,
                "status": "resolved",
                "resolution": summary,
            }
        )
        writes.append({"kind": "solution", "summary": summary, "issue_key": key})
    else:
        issue = _ISSUE.search(text)
        if issue:
            key = issue.group(1).upper()
            title = (issue.group(2) or briefing.get("headline") or key).strip().rstrip(".")[:200]
            writes.append(
                {
                    "kind": "issue",
                    "key": key,
                    "title": title[:200],
                    "description": title,
                    "status": "open",
                    "resolution": None,
                }
            )
        filed = _ISSUE_FILE.search(text)
        if filed and not issue:
            title = filed.group(1).strip().rstrip(".")[:200]
            key = _TICKET.search(text)
            writes.append(
                {
                    "kind": "issue",
                    "key": key.group(1).upper() if key else f"MEM-{_slug(title)[:24] or 'note'}",
                    "title": title,
                    "description": title,
                    "status": "open",
                    "resolution": None,
                }
            )
        solution = _SOLUTION.search(text)
        if solution:
            summary = solution.group(1).strip().rstrip(".")[:4000]
            ticket = _TICKET.search(text)
            writes.append(
                {
                    "kind": "solution",
                    "summary": summary,
                    "issue_key": ticket.group(1).upper() if ticket else None,
                }
            )

    return _dedupe(writes)


def apply_memory(store, repo_id: str, writes: list[dict], about_ids: list[str]) -> list[str]:
    applied: list[str] = []
    resolved_keys = {item["key"] for item in writes if item.get("kind") == "issue" and item.get("resolution")}
    seen_issue: set[str] = set()
    for item in writes:
        kind = item["kind"]
        try:
            if kind == "decision":
                store.add_decision(
                    repo_id,
                    item["title"],
                    item["rationale"],
                    "accepted",
                    about_ids[:8],
                    None,
                )
                applied.append(f"Decision: {item['title']}")
            elif kind == "issue":
                key = item["key"]
                if key in seen_issue:
                    continue
                seen_issue.add(key)
                store.add_issue(
                    repo_id,
                    key,
                    item["title"],
                    item.get("description") or item["title"],
                    item.get("status") or "open",
                    about_ids[:8],
                    item.get("resolution"),
                )
                applied.append(f"Issue: {key}")
            elif kind == "solution":
                if item.get("issue_key") in resolved_keys:
                    continue
                store.add_solution(
                    repo_id,
                    item["summary"],
                    item.get("issue_key"),
                    about_ids[:8],
                )
                applied.append(f"Solution: {item['summary'][:80]}")
        except (LookupError, AttributeError, TypeError):
            continue
    return applied


def _split_because(raw: str) -> tuple[str, str]:
    text = " ".join(raw.split()).strip().rstrip(".?")
    lowered = text.lower()
    marker = " because "
    if marker in lowered:
        idx = lowered.index(marker)
        title = text[:idx].strip()[:180]
        rationale = text[idx + len(marker) :].strip()[:4000]
        return title or text[:180], rationale or text
    return text[:180], text[:4000]


def _slug(title: str) -> str:
    cleaned = "".join(char.lower() if char.isalnum() else "-" for char in title)
    return "-".join(part for part in cleaned.split("-") if part)


def _dedupe(writes: list[dict]) -> list[dict]:
    seen: set[tuple] = set()
    unique: list[dict] = []
    for item in writes:
        key = (item["kind"], item.get("key"), item.get("title"), item.get("summary"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique
