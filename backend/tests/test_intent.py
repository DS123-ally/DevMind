from app.ingest.github import parse_github_url
from app.reasoning.intent import detect_intent


def test_github_url_parse():
    assert parse_github_url("https://github.com/acme/billing-service") == ("acme", "billing-service")
    assert parse_github_url("git@github.com:acme/billing-service.git") == ("acme", "billing-service")


def test_intent_kinds():
    assert detect_intent("Where is calculate_tax used?")["kind"] == "callers"
    assert detect_intent("What technologies does this project use?")["kind"] == "technologies"
    assert detect_intent("Why are we using stripe?")["kind"] == "why_technology"
    assert detect_intent("Have we seen this bug before?")["kind"] == "seen_bug"
    assert detect_intent("How was this issue fixed?")["kind"] == "how_fixed"
    assert detect_intent("What caused this issue?")["kind"] == "caused"
