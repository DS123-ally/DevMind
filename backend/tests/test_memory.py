from app.reasoning.memory import apply_memory, extract_memory


def test_decision_extraction_splits_because():
    writes = extract_memory(
        "remember that we decided to store money as integer cents because floats drifted",
        {},
    )
    kinds = [item["kind"] for item in writes]
    assert kinds == ["decision"]
    assert writes[0]["title"].lower().startswith("store money")
    assert "floated" in writes[0]["rationale"] or "drifted" in writes[0]["rationale"]


def test_issue_and_solution_from_resolved_ticket():
    writes = extract_memory(
        "we resolved BILL-14 by recording a stable payment key",
        {"headline": "Webhook retries"},
    )
    kinds = {item["kind"] for item in writes}
    assert "issue" in kinds
    assert "solution" in kinds
    issue = next(item for item in writes if item["kind"] == "issue")
    assert issue["key"] == "BILL-14"
    assert issue["status"] == "resolved"


def test_plain_question_does_not_invent_memory():
    assert extract_memory("What does calculate_tax do?", {}) == []


def test_apply_memory_calls_store():
    class Store:
        def __init__(self):
            self.calls = []

        def add_decision(self, *args):
            self.calls.append(("decision", args[1]))

        def add_issue(self, *args):
            self.calls.append(("issue", args[1]))

        def add_solution(self, *args):
            self.calls.append(("solution", args[1]))

    store = Store()
    writes = extract_memory("decision: use integer cents because tax drifted", {})
    applied = apply_memory(store, "repo", writes, [])
    assert any(item.startswith("Decision:") for item in applied)
    assert store.calls[0][0] == "decision"
