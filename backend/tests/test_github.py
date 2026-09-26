from app.ingest.github import _apply_repo_metadata, _ingest_issues, _ingest_pulls, parse_github_url
from app.ingest.model import IngestDocument


class _FakeResponse:
    status_code = 404

    def json(self):
        return []


class _FakeClient:
    def get(self, url: str):
        return _FakeResponse()


def test_parse_ssh_and_https():
    assert parse_github_url("https://github.com/acme/billing.git") == ("acme", "billing")
    assert parse_github_url("git@github.com:acme/billing.git") == ("acme", "billing")


def test_repo_metadata_issues_and_closing_pr():
    doc = IngestDocument(repo_id="repo-1", name="billing", path=".", summary=None)
    _apply_repo_metadata(
        doc,
        {
            "html_url": "https://github.com/acme/billing",
            "full_name": "acme/billing",
            "description": "Invoices in cents.",
            "default_branch": "main",
            "stargazers_count": 12,
            "forks_count": 3,
            "open_issues_count": 1,
            "language": "Python",
            "license": {"spdx_id": "MIT"},
            "private": False,
            "topics": ["payments"],
        },
        "acme",
        "billing",
        ["graph"],
    )
    assert doc.github_url == "https://github.com/acme/billing"
    assert doc.github["stars"] == 12
    assert "graph" in doc.github["topics"]
    assert doc.summary.startswith("Invoices")

    issue_ids = _ingest_issues(
        doc,
        [
            {
                "number": 14,
                "title": "Stripe webhook retries double-apply payments",
                "state": "closed",
                "body": "IntegrityError in app/webhooks.py apply_payment",
                "html_url": "https://github.com/acme/billing/issues/14",
                "user": {"login": "lena"},
                "labels": [{"name": "bug"}],
                "assignees": [{"login": "lena"}],
                "comments": 4,
                "closed_at": "2024-06-04T00:00:00Z",
            }
        ],
        {"app/webhooks.py": "file-webhooks"},
        {"apply_payment": [("fn-apply", "app/webhooks.py")]},
        {},
    )
    assert issue_ids["14"] == doc.issues[0].id
    assert doc.issues[0].labels == ["bug"]
    assert doc.errors[0].type == "IntegrityError"

    _ingest_pulls(
        doc,
        _FakeClient(),
        "acme",
        "billing",
        [
            {
                "number": 38,
                "title": "Make Stripe payment application idempotent",
                "body": "Fixes #14",
                "state": "closed",
                "merged_at": "2024-06-05T00:00:00Z",
                "html_url": "https://github.com/acme/billing/pull/38",
                "user": {"login": "lena"},
                "base": {"ref": "main"},
                "head": {"ref": "fix/webhook"},
                "labels": [{"name": "payments"}],
            }
        ],
        issue_ids,
        {},
        {},
        {},
    )
    pull = doc.pull_requests[0]
    assert pull.merged is True
    assert pull.status == "merged"
    assert pull.closes_issue_ids == [doc.issues[0].id]
    assert pull.base == "main"
