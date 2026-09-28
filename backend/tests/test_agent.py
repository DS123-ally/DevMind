from pathlib import Path

from app.config import Settings
from app.reasoning.agent import _compile, ask
from app.reasoning.intent import detect_intent

ROOT = Path(__file__).resolve().parents[2] / "examples" / "billing-service"


class FakeStore:
    def get_project(self, repo_id: str) -> dict:
        return {"repository": {"id": repo_id, "name": "Billing Service", "path": str(ROOT), "summary": "Invoice math."}}

    def overview(self, repo_id: str) -> dict:
        return {
            "repository": {"name": "Billing Service", "summary": "Invoice math."},
            "technologies": [{"name": "Python", "category": "language"}],
            "decisions": [],
            "files": [{"file": {"path": "app/pricing.py", "language": "python", "docstring": "Invoice money math."}, "defines": ["calculate_tax"]}],
            "conversations": [],
        }

    def search(self, repo_id: str, tokens: list[str], lucene: str) -> list[dict]:
        return [{"id": "fn-1", "label": "Function", "name": "calculate_tax", "score": 4}]

    def neighborhood(self, repo_id: str, seed_ids: list[str]) -> dict:
        return {
            "repository": {"name": "Billing Service", "summary": "Invoice math."},
            "nodes": [
                {
                    "id": "fn-1",
                    "labels": ["Function"],
                    "props": {
                        "name": "calculate_tax",
                        "qualifiedName": "app/pricing.py::calculate_tax",
                        "filePath": "app/pricing.py",
                        "line": 13,
                        "signature": "calculate_tax(subtotal_cents: int, rate_bps: int) -> int",
                        "docstring": "Apply a tax rate expressed in basis points to a cent amount.",
                    },
                }
            ],
            "calls": [],
            "extends": [],
            "imports": [],
            "uses": [],
            "decisions": [],
            "issues": [],
            "errors": [],
            "pulls": [],
            "conversations": [],
            "authors": [],
        }

    def why_path(self, repo_id: str, tokens: list[str]) -> list[dict]:
        return []

    def save_briefing(self, repo_id: str, briefing: dict, about_ids: list[str]) -> str:
        assert briefing["what"]
        return "conv-test"

    def recent_conversations(self, repo_id: str, limit: int = 5) -> list[dict]:
        return [{"question": "Why cents?", "headline": "Store money as integer cents", "createdAt": "2024-02-12"}]

    def add_decision(self, *args, **kwargs) -> dict:
        return {"id": "d1"}

    def add_issue(self, *args, **kwargs) -> dict:
        return {"id": "i1"}

    def add_solution(self, *args, **kwargs) -> dict:
        return {"id": "s1"}


def _settings() -> Settings:
    return Settings(
        neo4j_uri="bolt://localhost:7687",
        neo4j_user="neo4j",
        neo4j_password="x",
        neo4j_database="neo4j",
        llm_base_url="",
        llm_api_key="",
        llm_model="",
        github_token="",
        cache_dir=".",
        host="127.0.0.1",
        port=8000,
        cors_origins=(),
        ui_dir=".",
    )


def test_intent_kinds():
    assert detect_intent("What does calculate_tax do?")["kind"] in {"symbol", "overview"}
    assert detect_intent("Why are we using Redis?")["kind"] == "why_technology"
    assert detect_intent("Who calls apply_payment?")["kind"] == "callers"


def test_langgraph_node_order():
    compiled = _compile(FakeStore(), _settings())
    names = set(compiled.get_graph().nodes)
    assert "intent_classification" in names
    assert "graph_retrieval" in names
    assert "code_retrieval" in names
    assert "llm_response" in names
    assert "memory_extraction" in names
    assert "neo4j_updates" in names


def test_ask_runs_the_four_stages():
    briefing = ask(FakeStore(), _settings(), "repo-1", "What does calculate_tax do?", "what")
    labels = [step["label"] for step in briefing["steps"]]
    assert labels[:4] == ["Intent classification", "Graph retrieval", "Code retrieval", "LLM response"]
    assert "Memory extraction" in labels
    assert "Neo4j updates" in labels
    assert briefing["id"] == "conv-test"
    assert briefing["intent"] == "symbol"
    assert any(item["name"] == "calculate_tax" for item in briefing["citations"])
    assert any(item.get("kind") == "snippet" for item in briefing["citations"])
