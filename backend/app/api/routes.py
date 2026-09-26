"""HTTP API. Briefings are walks on the Neo4j graph, then stored back into it."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, FastAPI, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from neo4j.exceptions import Neo4jError

from app.config import REPO_ROOT, get_settings
from app.graph.crud import LABELS, RELS
from app.graph.store import QUERIES, SCHEMA
from app.ingest.github import GitHubError, clone_or_update, parse_github_url
from app.ingest.neo4j_ingest import ingest_to_neo4j
from app.ingest.pipeline import IngestLimitError
from app.reasoning.agent import ask, read_source

router = APIRouter(prefix="/api")


class IngestIn(BaseModel):
    path: str = Field(min_length=1, max_length=1024)
    name: str | None = Field(default=None, max_length=200)


class GitHubIn(BaseModel):
    url: str = Field(min_length=8, max_length=500)
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


class NodePatch(BaseModel):
    props: dict = Field(default_factory=dict)


ALLOWED_NODE_PROPS = {
    "title", "rationale", "status", "description", "summary", "name",
    "key", "message", "headline", "question", "source",
}


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
            raise HTTPException(
                status_code=503,
                detail="Neo4j is not connected. Check NEO4J_URI in .env or run docker compose up -d.",
            ) from exc
    return store


def _ingest(store, path: Path, name: str | None, github_url: str | None = None, github_token: str = "") -> dict:
    try:
        return ingest_to_neo4j(store, path, name, github_url=github_url, github_token=github_token)
    except IngestLimitError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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
    request.app.state.settings = get_settings()
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
        "llm": (
            f"{settings.llm_provider}:{settings.llm_model}" if settings.llm_enabled else "off"
        ),
        "github": "configured" if settings.github_token else "public-only",
        "error": request.app.state.neo4j_error,
    }


@router.get("/projects")
def projects(request: Request) -> dict:
    return {"projects": _store(request).list_projects()}


@router.post("/ingest")
def ingest(body: IngestIn, request: Request) -> dict:
    return _ingest(_store(request), _resolve_path(body.path), body.name)


@router.post("/ingest/github")
def ingest_github(body: GitHubIn, request: Request) -> dict:
    settings = request.app.state.settings
    try:
        parse_github_url(body.url)
        root = clone_or_update(body.url, Path(settings.cache_dir), settings.github_token)
    except GitHubError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    owner_repo = body.url.rstrip("/").split("github.com/")[-1].replace(".git", "")
    name = body.name or owner_repo.replace("/", " / ")
    return _ingest(
        _store(request),
        root,
        name,
        github_url=body.url,
        github_token=settings.github_token,
    )


@router.post("/ingest/upload")
async def ingest_upload(request: Request, archive: UploadFile = File(...)) -> dict:
    import shutil
    import zipfile
    from tempfile import mkdtemp

    if not archive.filename or not archive.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Upload a .zip of the repository.")
    workspace = Path(mkdtemp(prefix="devmind-upload-"))
    zip_path = workspace / "repo.zip"
    zip_path.write_bytes(await archive.read())
    extract = workspace / "src"
    extract.mkdir()
    try:
        with zipfile.ZipFile(zip_path) as zipped:
            zipped.extractall(extract)
    except zipfile.BadZipFile as exc:
        shutil.rmtree(workspace, ignore_errors=True)
        raise HTTPException(status_code=400, detail="The zip file could not be read.") from exc
    children = [path for path in extract.iterdir() if path.name != "__MACOSX"]
    root = children[0] if len(children) == 1 and children[0].is_dir() else extract
    try:
        return _ingest(_store(request), root, archive.filename[:-4])
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


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
        "githubUrl": repository.get("githubUrl"),
        "github": {
            "url": repository.get("githubUrl"),
            "owner": repository.get("githubOwner"),
            "name": repository.get("githubName"),
            "fullName": repository.get("githubFullName"),
            "stars": repository.get("githubStars"),
            "forks": repository.get("githubForks"),
            "language": repository.get("githubLanguage"),
            "license": repository.get("githubLicense"),
            "visibility": repository.get("githubVisibility"),
            "topics": json.loads(repository.get("githubTopicsJson") or "[]")
            if isinstance(repository.get("githubTopicsJson"), str)
            else repository.get("githubTopicsJson") or [],
            "defaultBranch": repository.get("defaultBranch") or repository.get("githubDefaultBranch"),
            "openIssues": repository.get("githubOpenIssues"),
            "homepage": repository.get("githubHomepage"),
        }
        if repository.get("githubUrl")
        else None,
        "languages": repository.get("languagesJson"),
        "technologies": found["technologies"],
        "decisions": found["decisions"],
        "inventory": store.inventory(project_id),
        "briefings": store.list_briefings(project_id),
        "memory": store.memory_panel(project_id),
    }


@router.get("/projects/{project_id}/tree")
def project_tree(project_id: str, request: Request) -> dict:
    tree = _store(request).tree(project_id)
    if tree is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    return tree


@router.get("/projects/{project_id}/graph")
def project_graph(project_id: str, request: Request) -> dict:
    store = _store(request)
    if store.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    return store.subgraph(project_id)


@router.get("/projects/{project_id}/files")
def project_file(project_id: str, path: str, request: Request) -> dict:
    store = _store(request)
    record = store.file_record(project_id, path)
    if record is None:
        raise HTTPException(status_code=404, detail="File is not in the graph.")
    try:
        content = read_source(record["root"], path)
    except (FileNotFoundError, PermissionError, OSError) as exc:
        raise HTTPException(status_code=404, detail=f"Could not read {path} from disk.") from exc
    return {"file": record["file"], "symbols": record["symbols"], "content": content}


@router.post("/projects/{project_id}/ask")
def project_ask(project_id: str, body: AskIn, request: Request) -> dict:
    if body.mode not in {None, "what", "why", "both"}:
        raise HTTPException(status_code=400, detail="Mode must be what, why, or both.")
    request.app.state.settings = get_settings()
    try:
        return ask(_store(request), request.app.state.settings, project_id, body.question.strip(), body.mode)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Neo4jError as exc:
        raise HTTPException(status_code=500, detail=str(exc.message) if getattr(exc, "message", None) else str(exc)) from exc


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


@router.get("/schema")
def graph_schema() -> dict:
    return {
        "labels": sorted(LABELS),
        "relationships": sorted(RELS),
        "constraints": len(SCHEMA),
        "queries": sorted(QUERIES),
    }


@router.get("/projects/{project_id}/nodes/{node_id}")
def get_node(project_id: str, node_id: str, request: Request) -> dict:
    found = _store(request).crud.read(node_id, project_id)
    if found is None:
        raise HTTPException(status_code=404, detail="Node not found.")
    return found


@router.patch("/projects/{project_id}/nodes/{node_id}")
def patch_node(project_id: str, node_id: str, body: NodePatch, request: Request) -> dict:
    props = {key: value for key, value in body.props.items() if key in ALLOWED_NODE_PROPS}
    if not props:
        raise HTTPException(status_code=400, detail="No updatable properties supplied.")
    try:
        return _store(request).crud.update(node_id, props, project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Node not found.") from exc


@router.delete("/projects/{project_id}/nodes/{node_id}")
def delete_node(project_id: str, node_id: str, request: Request) -> dict:
    removed = _store(request).crud.delete(node_id, project_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Node not found.")
    return {"deleted": node_id}


@router.post("/projects/{project_id}/seed")
def seed_project(project_id: str, request: Request) -> dict:
    store = _store(request)
    if store.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    return store.seed_graph(project_id)


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
        version="0.2.0",
        summary="Project memory for code: what it does, and why it works this way.",
        lifespan=lifespan,
    )
    application.include_router(router)
    return application

