"""Ingest a repository from the command line."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.config import get_settings
from app.graph.store import GraphStore
from app.ingest.neo4j_ingest import ingest_to_neo4j


def main() -> None:
    parser = argparse.ArgumentParser(description="Write a repository into the DevMind graph")
    parser.add_argument("--path", required=True)
    parser.add_argument("--name")
    args = parser.parse_args()
    settings = get_settings()
    store = GraphStore(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password, settings.neo4j_database)
    store.verify()
    store.ensure_schema()
    try:
        print(json.dumps(ingest_to_neo4j(store, Path(args.path), args.name), indent=2))
    finally:
        store.close()


if __name__ == "__main__":
    main()
