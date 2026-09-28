"""Pull Jira issues into the ingest document as Issue / Error / Solution nodes."""

from __future__ import annotations

from typing import Any

import httpx

from app.config import Settings
from app.ids import node_id
from app.ingest.github import _dev, _errors_from_body, _paths_in
from app.ingest.model import DeveloperRec, IngestDocument, IssueRec, SolutionRec
from app.ingest.resolve import resolve_targets


class JiraError(ValueError):
    pass


def fetch_jira_memory(
    settings: Settings,
    doc: IngestDocument,
    files_by_path: dict[str, str],
    symbols_by_name: dict[str, list[tuple[str, str]]],
    developers: dict[str, DeveloperRec],
) -> int:
    if not settings.jira_enabled:
        return 0
    project = settings.jira_project.strip()
    if not project:
        doc.warnings.append("Jira is configured but JIRA_PROJECT is empty; tickets were not imported.")
        return 0
    issues = _search(settings, project)
    return _ingest_jira_issues(doc, issues, files_by_path, symbols_by_name, developers)


def _search(settings: Settings, project: str) -> list[dict]:
    base = settings.jira_base_url.rstrip("/")
    auth = (settings.jira_email, settings.jira_api_token)
    payload = {
        "jql": f'project = "{project}" ORDER BY updated DESC',
        "maxResults": 50,
        "fields": [
            "summary",
            "description",
            "status",
            "assignee",
            "labels",
            "issuetype",
            "resolution",
            "comment",
            "updated",
        ],
    }
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    with httpx.Client(timeout=40.0, auth=auth, headers=headers) as client:
        response = client.post(f"{base}/rest/api/3/search/jql", json=payload)
        if response.status_code in {404, 410}:
            response = client.post(f"{base}/rest/api/3/search", json=payload)
        if response.status_code == 401:
            raise JiraError("Jira rejected the email or API token.")
        if response.status_code == 403:
            raise JiraError("Jira denied access to that project.")
        if response.status_code == 400:
            raise JiraError(response.text[:240] or "Jira JQL was rejected. Check JIRA_PROJECT.")
        response.raise_for_status()
        body = response.json()
    rows = body.get("issues") if isinstance(body, dict) else None
    return rows if isinstance(rows, list) else []


def _ingest_jira_issues(
    doc: IngestDocument,
    issues: list[dict],
    files_by_path: dict[str, str],
    symbols_by_name: dict[str, list[tuple[str, str]]],
    developers: dict[str, DeveloperRec],
) -> int:
    existing = {item.key for item in doc.issues}
    added = 0
    for item in issues:
        key = str(item.get("key") or "").strip()
        fields = item.get("fields") if isinstance(item.get("fields"), dict) else {}
        title = str(fields.get("summary") or "").strip()
        if not key or not title or key in existing:
            continue
        description = _adf_text(fields.get("description"))
        comments = _comments_text(fields.get("comment"))
        blob = f"{title}\n{description}\n{comments}"
        status_name = ((fields.get("status") or {}).get("name") or "open")
        status = _status(status_name)
        resolution = ((fields.get("resolution") or {}) or {}).get("name") if isinstance(fields.get("resolution"), dict) else None
        assignee = fields.get("assignee") if isinstance(fields.get("assignee"), dict) else {}
        assignee_name = str(assignee.get("displayName") or assignee.get("emailAddress") or "")
        if assignee_name:
            _dev(developers, doc.repo_id, assignee_name, assignee.get("emailAddress"))
        labels = [str(label) for label in fields.get("labels") or [] if label]
        issue_type = ((fields.get("issuetype") or {}) or {}).get("name")
        if issue_type:
            labels = [str(issue_type)] + labels
        error_ids = _errors_from_body(doc, blob, files_by_path, symbols_by_name)
        for error in doc.errors:
            if error.id in error_ids and error.message.endswith("GitHub issue."):
                error.message = f"{error.type} recorded from a Jira ticket."
                error.source = "jira"
        issue_id = node_id(doc.repo_id, "issue", key)
        url = f"{_browse_url(item, key)}"
        doc.issues.append(
            IssueRec(
                id=issue_id,
                key=key,
                title=title,
                status=status,
                description=description[:4000],
                source="jira",
                about_ids=resolve_targets(_paths_in(blob), files_by_path, symbols_by_name),
                caused_error_ids=error_ids,
                url=url,
                labels=labels,
                assignees=[assignee_name] if assignee_name else [],
                comments=len((fields.get("comment") or {}).get("comments") or []) if isinstance(fields.get("comment"), dict) else 0,
                closed_at=None if status == "open" else str(fields.get("updated") or "") or None,
            )
        )
        if resolution or status in {"resolved", "closed", "done"}:
            summary = str(resolution or comments or title).strip()[:400]
            if summary:
                doc.solutions.append(
                    SolutionRec(
                        id=node_id(doc.repo_id, "solution", f"jira-{key.lower()}"),
                        key=f"jira-{key.lower()}",
                        summary=summary,
                        source="jira",
                        resolves_issue_ids=[issue_id],
                        resolves_error_ids=error_ids,
                    )
                )
        existing.add(key)
        added += 1
    return added


def _status(name: str) -> str:
    lowered = name.strip().lower()
    if lowered in {"done", "closed", "resolved", "complete", "completed"}:
        return "resolved" if lowered != "closed" else "closed"
    if lowered in {"in progress", "in review"}:
        return "open"
    return "open" if lowered in {"to do", "todo", "open", "backlog", "new"} else lowered or "open"


def _browse_url(item: dict, key: str) -> str:
    self_url = str(item.get("self") or "")
    if "/rest/api/" in self_url:
        return self_url.split("/rest/api/")[0] + "/browse/" + key
    return key


def _comments_text(comment_field: Any) -> str:
    if not isinstance(comment_field, dict):
        return ""
    parts = []
    for row in comment_field.get("comments") or []:
        if isinstance(row, dict):
            parts.append(_adf_text(row.get("body")))
    return "\n".join(part for part in parts if part)


def _adf_text(node: Any) -> str:
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "\n".join(part for part in (_adf_text(item) for item in node) if part)
    if isinstance(node, dict):
        if node.get("type") == "text":
            return str(node.get("text") or "")
        return _adf_text(node.get("content"))
    return ""
