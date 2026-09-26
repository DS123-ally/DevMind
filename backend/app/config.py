"""Runtime configuration loaded from the environment and an optional .env file."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]


def load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if not os.environ.get(key):
            os.environ[key] = value


@dataclass(frozen=True)
class Settings:
    neo4j_uri: str
    neo4j_user: str
    neo4j_password: str
    neo4j_database: str
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    github_token: str
    cache_dir: str
    host: str
    port: int
    cors_origins: tuple[str, ...]
    ui_dir: str

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_base_url and self.llm_model and self.llm_api_key)

    @property
    def llm_provider(self) -> str:
        if "openrouter.ai" in self.llm_base_url:
            return "openrouter"
        if "graphacademy.neo4j.com" in self.llm_base_url:
            return "graphacademy"
        if "groq.com" in self.llm_base_url:
            return "groq"
        if self.llm_base_url:
            return "openai-compatible"
        return "off"


def get_settings() -> Settings:
    load_dotenv(REPO_ROOT / ".env")
    return Settings(
        neo4j_uri=os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
        neo4j_user=os.environ.get("NEO4J_USERNAME") or os.environ.get("NEO4J_USER", "neo4j"),
        neo4j_password=os.environ.get("NEO4J_PASSWORD", "devmindlocal"),
        neo4j_database=os.environ.get("NEO4J_DATABASE", "neo4j"),
        llm_base_url=_llm_base_url(),
        llm_api_key=os.environ.get("DEVMIND_LLM_API_KEY")
        or os.environ.get("OPENROUTER_API_KEY")
        or os.environ.get("GROQ_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or "",
        llm_model=_llm_model(),
        github_token=os.environ.get("GITHUB_TOKEN", ""),
        cache_dir=os.environ.get("DEVMIND_CACHE_DIR", str(REPO_ROOT / ".cache")),
        host=os.environ.get("DEVMIND_HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT") or os.environ.get("DEVMIND_PORT", "8000")),
        cors_origins=_cors_origins(),
        ui_dir=os.environ.get("DEVMIND_UI_DIR") or str(REPO_ROOT / "frontend" / "dist"),
    )


def _llm_provider_name() -> str:
    return os.environ.get("DEVMIND_LLM_PROVIDER", "").strip().lower()


def _llm_model() -> str:
    if _llm_provider_name() == "openrouter" or os.environ.get("OPENROUTER_API_KEY"):
        return (
            os.environ.get("DEVMIND_LLM_MODEL")
            or os.environ.get("OPENROUTER_MODEL")
            or "openrouter/free"
        )
    explicit = (
        os.environ.get("DEVMIND_LLM_MODEL")
        or os.environ.get("OPENAI_MODEL")
        or os.environ.get("GROQ_MODEL")
        or ""
    )
    if explicit:
        return explicit
    if _llm_base_url():
        return "gpt-4o-mini"
    return ""


def _llm_base_url() -> str:
    provider = _llm_provider_name()
    if provider == "openrouter" or os.environ.get("OPENROUTER_API_KEY"):
        return "https://openrouter.ai/api/v1"
    explicit = (
        os.environ.get("DEVMIND_LLM_BASE_URL")
        or os.environ.get("OPENAI_BASE_URL")
        or ""
    ).rstrip("/")
    if explicit:
        return explicit
    if os.environ.get("GROQ_API_KEY"):
        return "https://api.groq.com/openai/v1"
    if os.environ.get("OPENAI_API_KEY"):
        return "https://api.openai.com/v1"
    return ""


def _cors_origins() -> tuple[str, ...]:
    defaults = (
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:5174",
        "http://localhost:5174",
        "http://127.0.0.1:3000",
        "http://localhost:3000",
        "http://127.0.0.1:8000",
        "http://localhost:8000",
    )
    extra = tuple(
        origin.strip().rstrip("/")
        for origin in os.environ.get("DEVMIND_CORS_ORIGINS", "").split(",")
        if origin.strip()
    )
    seen: set[str] = set()
    ordered: list[str] = []
    for origin in defaults + extra:
        if origin not in seen:
            seen.add(origin)
            ordered.append(origin)
    return tuple(ordered)
