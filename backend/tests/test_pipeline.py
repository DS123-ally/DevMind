from pathlib import Path

from app.ingest.pipeline import scan

ROOT = Path(__file__).resolve().parents[2] / "examples" / "billing-service"


def _symbol(document, name: str):
    matches = [item for item in document.symbols if item.name == name]
    assert len(matches) == 1, name
    return matches[0]


def test_billing_service_graph_document():
    document = scan(ROOT, "Billing Service")

    calculate_tax = _symbol(document, "calculate_tax")
    preview = _symbol(document, "preview_invoice")
    apply_payment = _symbol(document, "apply_payment")
    record_payment = _symbol(document, "record_payment")
    handle = _symbol(document, "handle_stripe_event")

    assert (preview.id, calculate_tax.id) in document.calls
    assert (handle.id, apply_payment.id) in document.calls
    assert (apply_payment.id, record_payment.id) in document.calls

    cents = next(item for item in document.decisions if item.slug == "0001-use-integer-cents")
    floats = next(item for item in document.decisions if item.slug == "0000-use-floating-point-dollars")
    webhook = next(item for item in document.decisions if "at-least-once" in item.slug)
    assert cents.supersedes_slug == floats.slug
    assert cents.status == "accepted"
    assert floats.status == "superseded"
    assert calculate_tax.id in cents.about_ids
    assert apply_payment.id in webhook.about_ids
    assert "Lena Ortiz" in [developer.name for developer in document.developers]

    issue = document.issues[0]
    assert issue.key == "BILL-14"
    assert apply_payment.id in issue.about_ids
    assert document.errors[0].id in issue.caused_error_ids
    solution = document.solutions[0]
    assert issue.id in solution.resolves_issue_ids
    assert document.errors[0].id in solution.resolves_error_ids
    assert issue.id in document.pull_requests[0].closes_issue_ids

    names = {item.name for item in document.technologies}
    assert "stripe" in names
    assert "fastapi" in names
    assert document.pull_requests[0].number == 38
    assert document.summary
    assert document.memory_loaded is True
