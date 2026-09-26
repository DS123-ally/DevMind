from app.reasoning.llm import _parse_json


def test_parse_json_from_markdown_fence():
    parsed = _parse_json('```json\n{"headline": "Tax", "what": ["calculate_tax"], "why": []}\n```')
    assert parsed == {"headline": "Tax", "what": ["calculate_tax"], "why": []}
