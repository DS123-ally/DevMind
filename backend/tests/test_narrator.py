from app.reasoning.facts import BriefingFacts, DecisionFact, SymbolFact
from app.reasoning.narrator import grounded_bullets, narrate


def test_why_without_a_decision_reports_the_gap():
    facts = BriefingFacts(
        question="Why is the cache process-local?",
        mode="why",
        repository="Billing Service",
        matched=True,
        symbols=[
            SymbolFact(
                kind="function",
                name="calculate_tax",
                qualified_name="app/pricing.py::calculate_tax",
                file="app/pricing.py",
                line=8,
                signature="calculate_tax(subtotal_cents: int, rate_bps: int) -> int",
                docstring="Apply a tax rate expressed in basis points to a cent amount.",
            )
        ],
    )
    briefing = narrate(facts)
    assert any("No technical decision" in gap for gap in briefing["gaps"])
    assert "calculate_tax" in briefing["what"][0]
    assert briefing["voice"] == "graph"


def test_accepted_decision_leads_and_names_what_it_supersedes():
    facts = BriefingFacts(
        question="Why are amounts stored in integer cents?",
        mode="why",
        repository="Billing Service",
        matched=True,
        decisions=[
            DecisionFact(
                title="Store money as integer cents",
                status="accepted",
                rationale="Totals drifted when tax used binary floats.",
                deciders=["Lena Ortiz"],
                supersedes=["Use floating-point dollars"],
                about=["calculate_tax"],
            ),
            DecisionFact(
                title="Use floating-point dollars",
                status="superseded",
                rationale="The prototype used floats.",
            ),
        ],
    )
    briefing = narrate(facts)
    assert briefing["headline"] == "Store money as integer cents"
    assert "supersedes" in briefing["why"][0]
    assert any("Superseded decision" in line for line in briefing["why"])
    assert briefing["gaps"] == []


def test_model_wording_cannot_introduce_an_ungrounded_reason():
    corpus = {"integer", "cents", "calculate_tax", "pricing"}
    kept = grounded_bullets(
        [
            "calculate_tax uses integer cents.",
            "The team chose Redis because the CFO preferred it.",
        ],
        corpus,
    )
    assert kept == ["calculate_tax uses integer cents."]
