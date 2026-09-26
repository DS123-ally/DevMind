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

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_base_url and self.llm_model)


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
        llm_model=os.environ.get("DEVMIND_LLM_MODEL")
        or os.environ.get("OPENAI_MODEL")
        or os.environ.get("OPENROUTER_MODEL")
        or os.environ.get("GROQ_MODEL")
        or ("gpt-4o-mini" if _llm_base_url() else ""),
        github_token=os.environ.get("GITHUB_TOKEN", ""),
        cache_dir=os.environ.get("DEVMIND_CACHE_DIR", str(REPO_ROOT / ".cache")),
        host=os.environ.get("DEVMIND_HOST", "127.0.0.1"),
        port=int(os.environ.get("DEVMIND_PORT", "8000")),
    )


def _llm_base_url() -> str:
    explicit = (
        os.environ.get("DEVMIND_LLM_BASE_URL")
        or os.environ.get("OPENAI_BASE_URL")
        or ""
    ).rstrip("/")
    if explicit:
        return explicit
    if os.environ.get("OPENROUTER_API_KEY"):
        return "https://openrouter.ai/api/v1"
    if os.environ.get("GROQ_API_KEY"):
        return "https://api.groq.com/openai/v1"
    if os.environ.get("OPENAI_API_KEY"):
        return "https://api.openai.com/v1"
    return ""
