from fastapi.testclient import TestClient

from app.api.routes import create_app


def test_schema_catalog():
    client = TestClient(create_app())
    response = client.get("/api/schema")
    assert response.status_code == 200
    body = response.json()
    assert "Repository" in body["labels"]
    assert "CHOOSES" in body["relationships"]
    assert "why_path" in body["queries"]
    assert body["constraints"] >= 14
