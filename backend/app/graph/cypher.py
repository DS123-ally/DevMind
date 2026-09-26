"""Split and load .cypher files used as the schema / query / seed catalog."""

from __future__ import annotations

from pathlib import Path

GRAPH_DIR = Path(__file__).resolve().parent


def statements(path: Path) -> list[str]:
    chunks: list[str] = []
    buf: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if stripped.startswith("//"):
            if not buf:
                continue
        if not stripped and not buf:
            continue
        buf.append(raw)
        if stripped.endswith(";"):
            stmt = "\n".join(buf).strip().rstrip(";").strip()
            if stmt:
                chunks.append(stmt)
            buf = []
    leftover = "\n".join(buf).strip().rstrip(";").strip()
    if leftover:
        chunks.append(leftover)
    return chunks


def load_schema() -> list[str]:
    return statements(GRAPH_DIR / "schema.cypher")


def named_queries() -> dict[str, str]:
    found: dict[str, str] = {}
    name: str | None = None
    buf: list[str] = []
    path = GRAPH_DIR / "queries.cypher"
    for raw in path.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if stripped.startswith("// name:"):
            if name and buf:
                found[name] = "\n".join(buf).strip().rstrip(";")
            name = stripped.split(":", 1)[1].strip()
            buf = []
            continue
        if stripped.startswith("//") or not stripped:
            continue
        buf.append(raw)
        if stripped.endswith(";") and name:
            found[name] = "\n".join(buf).strip().rstrip(";")
            name = None
            buf = []
    return found
