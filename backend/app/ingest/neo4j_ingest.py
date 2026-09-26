"""Write a scanned repository into Neo4j (schema + nodes + relationships)."""

from __future__ import annotations

from pathlib import Path

from app.graph.store import GraphStore
from app.ingest.pipeline import scan


def ingest_to_neo4j(
    store: GraphStore,
    root: Path,
    name: str | None = None,
    github_url: str | None = None,
    github_token: str = "",
) -> dict:
    store.ensure_schema()
    document = scan(root, name, github_url=github_url, github_token=github_token)
    return store.apply(document)
