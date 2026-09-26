"""DevMind API process. Neo4j is required for memory; the process still boots when it is down."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from neo4j.exceptions import Neo4jError

from app.api.routes import create_app
from app.config import get_settings
from app.graph.store import GraphStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logging.getLogger("neo4j.notifications").setLevel(logging.WARNING)
logger = logging.getLogger("devmind")


def _connect(application: FastAPI) -> None:
    settings = application.state.settings
    store = application.state.store
    if store is None:
        try:
            store = GraphStore(
                settings.neo4j_uri,
                settings.neo4j_user,
                settings.neo4j_password,
                settings.neo4j_database,
            )
        except Exception as exc:
            logger.warning("Neo4j driver could not be created: %s", exc)
            application.state.store = None
            application.state.neo4j_ok = False
            application.state.neo4j_error = str(exc)
            return
        application.state.store = store
    try:
        store.verify()
        store.ensure_schema()
    except (OSError, Neo4jError, Exception) as exc:
        logger.warning("Neo4j is unavailable: %s", exc)
        application.state.neo4j_ok = False
        application.state.neo4j_error = str(exc)
        return
    application.state.neo4j_ok = True
    application.state.neo4j_error = None
    logger.info("Connected to Neo4j at %s", settings.neo4j_uri)


@asynccontextmanager
async def lifespan(application: FastAPI):
    application.state.settings = get_settings()
    application.state.store = None
    application.state.neo4j_ok = False
    application.state.neo4j_error = None
    _connect(application)
    yield
    store = application.state.store
    if store is not None:
        store.close()


def build_app() -> FastAPI:
    settings = get_settings()
    application = create_app(lifespan=lifespan)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["*"],
        allow_headers=["*"],
    )
    ui = Path(settings.ui_dir)
    if ui.is_dir() and (ui / "index.html").is_file():
        application.mount("/", StaticFiles(directory=str(ui), html=True), name="ui")
        logger.info("Serving UI from %s", ui)
    return application


app = build_app()
