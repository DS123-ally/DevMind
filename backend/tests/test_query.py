from app.reasoning.query import detect_mode, tokenize


def test_project_level_question_has_no_search_tokens():
    assert tokenize("Why does the project work this way?") == []
    assert tokenize("What does this project do?") == []


def test_specific_question_keeps_identifiers():
    assert tokenize("Why are amounts stored in integer cents?") == ["amounts", "stored", "integer", "cents"]
    assert tokenize("What does calculate_tax do?") == ["calculate_tax"]


def test_mode_detection():
    assert detect_mode("Why are amounts stored in integer cents?") == "why"
    assert detect_mode("What does calculate_tax do?") == "what"
    assert detect_mode("What does calculate_tax do and why is the math integer?") == "both"
    assert detect_mode("Tell me about calculate_tax", "why") == "why"
