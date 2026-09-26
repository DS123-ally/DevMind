"""HTTP API. Briefings are written from the graph and then stored back into it."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from app.config import REPO_ROOT
from app.ingest.pipeline import IngestLimitError, scan
from app.reasoning.engine import ask

router = APIRouter(prefix="/api")


class IngestIn(BaseModel):
    path: str = Field(min_length=1, max_length=1024)
    name: str | None = Field(default=None, max_length=200)


class AskIn(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    mode: str | None = None


class DecisionIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    rationale: str = Field(min_length=3, max_length=4000)
    status: str = "accepted"
    decider: str | None = None
    aboutIds: list[str] = Field(default_factory=list)


class IssueIn(BaseModel):
    key: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=3, max_length=200)
    description: str = ""
    status: str = "open"
    aboutIds: list[str] = Field(default_factory=list)
    resolution: str | None = None


def _store(request: Request):
    store = request.app.state.store
    if store is None:
        raise HTTPException(status_code=503, detail="Neo4j driver is not configured.")
    if not request.app.state.neo4j_ok:
        try:
            store.verify()
            store.ensure_schema()
            request.app.state.neo4j_ok = True
            request.app.state.neo4j_error = None
        except Exception as exc:
            request.app.state.neo4j_error = str(exc)
            raise HTTPException(status_code=503, detail="Neo4j is not connected. Start it with docker compose up -d.") from exc
    return store


def _ingest(store, path: Path, name: str | None) -> dict:
    try:
        document = scan(path, name)
    except IngestLimitError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return store.apply(document)


def _resolve_path(raw: str) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        path = REPO_ROOT / path
    path = path.resolve()
    if not path.is_dir():
        raise HTTPException(status_code=400, detail=f"{path} is not a directory.")
    return path


@router.get("/health")
def health(request: Request) -> dict:
    settings = request.app.state.settings
    store = request.app.state.store
    if store is not None and not request.app.state.neo4j_ok:
        try:
            store.verify()
            store.ensure_schema()
            request.app.state.neo4j_ok = True
            request.app.state.neo4j_error = None
        except Exception as exc:
            request.app.state.neo4j_error = str(exc)
    connected = bool(request.app.state.neo4j_ok)
    return {
        "status": "ok" if connected else "degraded",
        "neo4j": "connected" if connected else "unavailable",
        "llm": "configured" if settings.llm_enabled else "off",
        "error": request.app.state.neo4j_error,
    }


@router.get("/projects")
def projects(request: Request) -> dict:
    return {"projects": _store(request).list_projects()}


@router.post("/ingest")
def ingest(body: IngestIn, request: Request) -> dict:
    return _ingest(_store(request), _resolve_path(body.path), body.name)


@router.post("/demo/billing")
def demo_billing(request: Request) -> dict:
    return _ingest(_store(request), REPO_ROOT / "examples" / "billing-service", "Billing Service")


@router.post("/demo/self")
def demo_self(request: Request) -> dict:
    return _ingest(_store(request), REPO_ROOT, "DevMind")


@router.get("/projects/{project_id}")
def project(project_id: str, request: Request) -> dict:
    store = _store(request)
    found = store.get_project(project_id)
    if found is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    repository = found["repository"]
    return {
        "id": project_id,
        "name": repository.get("name"),
        "path": repository.get("path"),
        "summary": repository.get("summary"),
        "updatedAt": repository.get("updatedAt"),
        "technologies": found["technologies"],
        "decisions": found["decisions"],
        "inventory": store.inventory(project_id),
        "briefings": store.list_briefings(project_id),
    }


@router.get("/projects/{project_id}/tree")
def project_tree(project_id: str, request: Request) -> dict:
    tree = _store(request).tree(project_id)
    if tree is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    return tree


@router.post("/projects/{project_id}/ask")
def project_ask(project_id: str, body: AskIn, request: Request) -> dict:
    if body.mode not in {None, "what", "why", "both"}:
        raise HTTPException(status_code=400, detail="Mode must be what, why, or both.")
    try:
        return ask(_store(request), request.app.state.settings, project_id, body.question.strip(), body.mode)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/projects/{project_id}/decisions")
def project_decision(project_id: str, body: DecisionIn, request: Request) -> dict:
    try:
        return _store(request).add_decision(
            project_id,
            body.title.strip(),
            body.rationale.strip(),
            body.status.strip().lower() or "accepted",
            body.aboutIds,
            body.decider.strip() if body.decider else None,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Project not found.") from exc


@router.post("/projects/{project_id}/issues")
def project_issue(project_id: str, body: IssueIn, request: Request) -> dict:
    try:
        return _store(request).add_issue(
            project_id,
            body.key.strip(),
            body.title.strip(),
            body.description.strip(),
            body.status.strip().lower() or "open",
            body.aboutIds,
            body.resolution.strip() if body.resolution else None,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Project not found.") from exc


def create_app(lifespan=None) -> FastAPI:
    application = FastAPI(
        title="DevMind",
        version="0.1.0",
        summary="Project memory for code: what it does, and why it works this way.",
        lifespan=lifespan,
    )
    application.include_router(router)
    return application
