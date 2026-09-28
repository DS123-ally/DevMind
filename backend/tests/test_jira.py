from app.ingest.jira import _adf_text, _ingest_jira_issues, _status
from app.ingest.model import IngestDocument


def test_adf_flattens_description():
    text = _adf_text(
        {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "IntegrityError in app/webhooks.py apply_payment"}],
                }
            ],
        }
    )
    assert "IntegrityError" in text
    assert "apply_payment" in text


def test_jira_ticket_becomes_issue_and_solution():
    doc = IngestDocument(repo_id="repo-1", name="billing", path=".", summary=None)
    added = _ingest_jira_issues(
        doc,
        [
            {
                "key": "BILL-14",
                "self": "https://acme.atlassian.net/rest/api/3/issue/10014",
                "fields": {
                    "summary": "Stripe webhook retries double-apply payments",
                    "description": {
                        "type": "doc",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [{"type": "text", "text": "IntegrityError in app/webhooks.py"}],
                            }
                        ],
                    },
                    "status": {"name": "Done"},
                    "resolution": {"name": "Record a stable payment key"},
                    "assignee": {"displayName": "Lena Ortiz", "emailAddress": "lena@example.com"},
                    "labels": ["payments"],
                    "issuetype": {"name": "Bug"},
                    "comment": {"comments": []},
                    "updated": "2024-06-04T00:00:00.000+0000",
                },
            }
        ],
        {"app/webhooks.py": "file-webhooks"},
        {"apply_payment": [("fn-apply", "app/webhooks.py")]},
        {},
    )
    assert added == 1
    assert doc.issues[0].key == "BILL-14"
    assert doc.issues[0].source == "jira"
    assert doc.issues[0].status == "resolved"
    assert doc.solutions[0].resolves_issue_ids == [doc.issues[0].id]
    assert doc.errors[0].type == "IntegrityError"


def test_jira_status_mapping():
    assert _status("To Do") == "open"
    assert _status("Done") == "resolved"
    assert _status("Closed") == "closed"
