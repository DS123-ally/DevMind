from app.config import _cors_origins


def test_cors_origins_include_local_and_extras(monkeypatch):
    monkeypatch.setenv("DEVMIND_CORS_ORIGINS", "https://devmind.onrender.com, https://app.example.com/")
    origins = _cors_origins()
    assert "http://127.0.0.1:5173" in origins
    assert "https://devmind.onrender.com" in origins
    assert "https://app.example.com" in origins
