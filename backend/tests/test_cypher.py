from app.graph.cypher import load_schema, named_queries, statements
from app.graph.cypher import GRAPH_DIR


def test_schema_statements():
    schema = load_schema()
    assert any("repository_id" in item for item in schema)
    assert any("FULLTEXT INDEX devmind_search" in item for item in schema)
    assert all(not item.endswith(";") for item in schema)


def test_named_queries():
    queries = named_queries()
    assert "why_path" in queries
    assert "list_projects" in queries
    assert "$repoId" in queries["why_path"]


def test_seed_statements():
    seed = statements(GRAPH_DIR / "seed.cypher")
    assert len(seed) >= 10
    assert any("BILL-14" in item for item in seed)
    assert any("CHOOSES" in item for item in seed)
