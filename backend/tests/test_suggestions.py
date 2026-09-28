from app.reasoning.suggestions import suggested_questions


def test_suggestions_use_functions_decisions_and_tickets():
    questions = suggested_questions(
        ["_private", "main", "calculate_tax", "apply_payment", "format_money"],
        ["Store money as integer cents", "Why is apply_payment safe to retry"],
        ["note", "BILL-14", "BILL-14", "DEV-2"],
    )
    texts = [item["text"] for item in questions]
    assert texts == [
        "What does calculate_tax do?",
        "What does apply_payment do?",
        "Why store money as integer cents?",
        "Why is apply_payment safe to retry?",
        "What happened with BILL-14?",
        "What happened with DEV-2?",
    ]
    assert questions[0]["mode"] == "what"
    assert questions[2]["mode"] == "why"


def test_empty_graph_has_no_invented_questions():
    assert suggested_questions(["a", "run"], ["short"], ["not-a-ticket"]) == []
