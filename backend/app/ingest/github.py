"""Clone a GitHub repository and pull issues and pull requests into the ingest document."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import httpx

from app.ids import node_id
from app.ingest.model import DeveloperRec, ErrorRec, IngestDocument, IssueRec, PullRequestRec
from app.ingest.resolve import resolve_targets

_GITHUB = re.compile(r"github\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/#?]+)", re.IGNORECASE)
_CLOSE = re.compile(r"\b(?:fix(?:es|ed)?|close[sd]?|resolve[sd]?)\s+#(\d+)\b", re.IGNORECASE)
_ERROR = re.compile(r"\b([A-Z][A-Za-z]+Error)\b")


class GitHubError(ValueError):
    pass


def parse_github_url(url: str) -> tuple[str, str]:
    match = _GITHUB.search(url.strip())
    if not match:
        raise GitHubError("Use a GitHub URL such as https://github.com/owner/repo")
    return match.group("owner"), match.group("repo").removesuffix(".git")


def clone_or_update(url: str, cache_dir: Path, token: str = "") -> Path:
    owner, name = parse_github_url(url)
    target = cache_dir / "repos" / f"{owner}__{name}"
    target.parent.mkdir(parents=True, exist_ok=True)
    remote = f"https://github.com/{owner}/{name}.git"
    if token:
        remote = f"https://x-access-token:{token}@github.com/{owner}/{name}.git"
    if (target / ".git").is_dir():
        completed = subprocess.run(
            ["git", "-C", str(target), "pull", "--ff-only"],
            capture_output=True,
            text=True,
            timeout=120,
        )
    else:
        completed = subprocess.run(
            ["git", "clone", "--depth", "1", remote, str(target)],
            capture_output=True,
            text=True,
            timeout=180,
        )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "git failed").strip().splitlines()[-1]
        raise GitHubError(f"Could not clone {owner}/{name}: {detail}")
    return target


def fetch_github_memory(
    url: str,
    token: str,
    doc: IngestDocument,
    files_by_path: dict[str, str],
    symbols_by_name: dict[str, list[tuple[str, str]]],
    developers: dict[str, DeveloperRec],
) -> None:
    owner, name = parse_github_url(url)
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "DevMind"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with httpx.Client(timeout=40.0, headers=headers) as client:
        repo = _get(client, f"https://api.github.com/repos/{owner}/{name}")
        issues = _pages(client, f"https://api.github.com/repos/{owner}/{name}/issues?state=all&per_page=50")
        pulls = _pages(client, f"https://api.github.com/repos/{owner}/{name}/pulls?state=all&per_page=50")
    doc.github_url = repo.get("html_url") or f"https://github.com/{owner}/{name}"
    doc.default_branch = repo.get("default_branch") or "main"
    if not doc.summary and repo.get("description"):
        doc.summary = str(repo["description"])[:600]

    issue_ids: dict[str, str] = {item.key: item.id for item in doc.issues}
    for item in issues:
        if item.get("pull_request"):
            continue
        number = item.get("number")
        title = str(item.get("title") or "").strip()
        if not isinstance(number, int) or not title:
            continue
        key = str(number)
        issue_id = node_id(doc.repo_id, "issue", key)
        issue_ids[key] = issue_id
        body = str(item.get("body") or "")
        error_ids = _errors_from_body(doc, body, files_by_path, symbols_by_name)
        login = ((item.get("user") or {}).get("login")) or ""
        if login:
            _dev(developers, doc.repo_id, login, None)
        doc.issues.append(
            IssueRec(
                id=issue_id,
                key=key,
                title=title,
                status=str(item.get("state") or "open"),
                description=body[:4000],
                source="github",
                about_ids=resolve_targets(_paths_in(body), files_by_path, symbols_by_name),
                caused_error_ids=error_ids,
                url=str(item.get("html_url") or "") or None,
            )
        )

    for item in pulls:
        number = item.get("number")
        title = str(item.get("title") or "").strip()
        if not isinstance(number, int) or not title:
            continue
        body = str(item.get("body") or "")
        login = ((item.get("user") or {}).get("login")) or ""
        author_id = _dev(developers, doc.repo_id, login, None) if login else None
        closes = []
        for match in _CLOSE.finditer(f"{title}\n{body}"):
            target = issue_ids.get(match.group(1))
            if target:
                closes.append(target)
        files = _pr_files(token, owner, name, number)
        doc.pull_requests.append(
            PullRequestRec(
                id=node_id(doc.repo_id, "pullrequest", str(number)),
                number=number,
                title=title,
                status=str(item.get("state") or "open"),
                source="github",
                url=str(item.get("html_url") or "") or None,
                author_id=author_id,
                file_ids=resolve_targets(files, files_by_path, symbols_by_name),
                closes_issue_ids=closes,
                body=body[:4000],
            )
        )


def _pr_files(token: str, owner: str, name: str, number: int) -> list[str]:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "DevMind"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with httpx.Client(timeout=30.0, headers=headers) as client:
            rows = _get(client, f"https://api.github.com/repos/{owner}/{name}/pulls/{number}/files")
    except GitHubError:
        return []
    if not isinstance(rows, list):
        return []
    return [str(row.get("filename")) for row in rows if row.get("filename")][:40]


def _errors_from_body(
    doc: IngestDocument,
    body: str,
    files_by_path: dict[str, str],
    symbols_by_name: dict[str, list[tuple[str, str]]],
) -> list[str]:
    found: list[str] = []
    for match in _ERROR.finditer(body):
        kind = match.group(1)
        error_id = node_id(doc.repo_id, "error", kind.lower())
        if any(item.id == error_id for item in doc.errors):
            found.append(error_id)
            continue
        doc.errors.append(
            ErrorRec(
                id=error_id,
                key=kind.lower(),
                type=kind,
                message=f"{kind} recorded from a GitHub issue.",
                source="github",
                about_ids=resolve_targets(_paths_in(body), files_by_path, symbols_by_name),
            )
        )
        found.append(error_id)
    return found


def _paths_in(text: str) -> list[str]:
    return re.findall(r"[\w./-]+\.(?:py|ts|tsx|js|jsx|go|rs|java|md)", text)[:12]


def _dev(developers: dict[str, DeveloperRec], repo_id: str, name: str, email: str | None) -> str:
    from app.ids import person_key

    key = person_key(name, email)
    dev_id = node_id(repo_id, "developer", key)
    if dev_id not in developers:
        developers[dev_id] = DeveloperRec(id=dev_id, name=name, email=(email or "").lower())
    return dev_id


def _get(client: httpx.Client, url: str):
    response = client.get(url)
    if response.status_code == 404:
        raise GitHubError("GitHub repository not found or it is private without GITHUB_TOKEN.")
    if response.status_code == 401:
        raise GitHubError("GitHub rejected the token.")
    if response.status_code == 403:
        raise GitHubError("GitHub rate-limited the request. Set GITHUB_TOKEN in .env.")
    response.raise_for_status()
    return response.json()


def _pages(client: httpx.Client, url: str) -> list[dict]:
    rows: list[dict] = []
    next_url: str | None = url
    while next_url and len(rows) < 80:
        response = client.get(next_url)
        if response.status_code >= 400:
            _get(client, next_url)
        payload = response.json()
        if not isinstance(payload, list):
            break
        rows.extend(item for item in payload if isinstance(item, dict))
        next_url = _next_link(response.headers.get("link", ""))
    return rows


def _next_link(header: str) -> str | None:
    for part in header.split(","):
        if 'rel="next"' in part:
            match = re.search(r"<([^>]+)>", part)
            if match:
                return match.group(1)
    return None
