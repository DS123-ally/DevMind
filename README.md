# DevMind

DevMind is a coding assistant that remembers a repository as a graph. Neo4j is the system of record. A briefing is a walk over that graph, not a chat reply with a database hiding behind it.

It answers two different questions:

- **What** does the code do? Files, classes, functions, calls, imports, technologies.
- **Why** does the project work this way? Technical decisions, issues, errors, solutions, pull requests, developers, and earlier conversations.

If the graph has no recorded reason, the briefing says so.

## Graph

| Node | What it remembers |
| --- | --- |
| Repository | The project that was ingested |
| Directory, File | The tree, language, module docstring, imports |
| Class, Function | Definitions, signatures, docstrings, line numbers |
| Technology | Libraries and runtimes detected from manifests and imports |
| Decision | An ADR, a `.devmind/memory.json` entry, or a decision you record later |
| Issue, Error, Solution | Incidents and the fix that resolved them |
| PullRequest | A change set and its author |
| Developer | Deciders, pull-request authors, and git authors |
| Conversation, Message | A briefing written back into the graph, linked to the nodes it used |

Relationships include `CONTAINS`, `DEFINES`, `CALLS`, `IMPORTS`, `EXTENDS`, `USES`, `HAS_ISSUE`, `HAS_PR`, `CAUSED`, `CHOOSES`, `INFORMS`, `CLOSES`, `ABOUT`, `DECIDED_BY`, `SUPERSEDES`, `AFFECTS`, `OCCURS_IN`, `RESOLVES`, `CHANGES`, `AUTHORED_BY`, `AUTHORED`, `WORKS_ON`, `IN_REPOSITORY`, and `HAS_MESSAGE`.

Re-ingesting a repository rebuilds the code structure and refreshes ADR and `.devmind/memory.json` nodes. Decisions you record in the UI (`source: user`) stay.

## How a briefing is produced

1. **Intent classification** — callers, technologies, bugs, how-fixed, why-technology, overview.
2. **Graph retrieval** — bounded Neo4j subgraph (not a chat log).
3. **Code retrieval** — source windows around the matched symbols.
4. **LLM response** — optional rephrase, grounded in graph facts and those windows.
5. **Memory extraction** — explicit decisions, issues, and solutions from the question (nothing invented).
6. **Neo4j updates** — Conversation stored; extracted Decision / Issue / Solution nodes linked to the subgraph.
7. Citations and the WHY path (`Technology → Decision → Issue → Solution → PR`).

Say `remember that we decided … because …`, `issue BILL-14: …`, or `we resolved BILL-14 by …` to write those nodes.

Open `http://127.0.0.1:5173` (Vite) or `http://127.0.0.1:3000` (Next.js + React Flow). Connect a GitHub repo with the GitHub URL field (`GITHUB_TOKEN` in `.env` for private repos). Zip upload: `POST /api/ingest/upload`.

Jira Cloud tickets: set `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`, and `JIRA_PROJECT` in `.env`, then ingest the matching repository. Tickets become Issue nodes (and Solution nodes when the ticket is Done). Do not put a Jira token in `GITHUB_TOKEN`.

## Run it

Neo4j:

```bash
docker compose up -d
```

API (from `backend`):

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

On macOS or Linux, activate with `source .venv/bin/activate`.

UI (from `frontend`):

```bash
npm install
npm run dev
```

Open `http://127.0.0.1:5173`.

Next.js console with an interactive graph (from `web`):

```bash
npm install
npm run dev
```

Open `http://127.0.0.1:3000`.

## Deploy

One Docker image serves the UI and `/api` on the same origin. Point it at **Neo4j Aura** and **OpenRouter** with the same keys you use locally (never put `.env` in git).

### Local production image

```bash
docker compose -f docker-compose.prod.yml up --build
```

Open `http://127.0.0.1:8000`. GitHub clones are stored in a Docker volume.

### Render

1. Push this repo to GitHub.
2. New Web Service → this repository → Docker.
3. Or Blueprint: `render.yaml`.
4. Set `NEO4J_URI`, `NEO4J_PASSWORD`, `OPENROUTER_API_KEY`.
5. After the first deploy, set `DEVMIND_CORS_ORIGINS` to your Render URL if the UI is ever hosted separately. Same-origin Docker does not need it.

Railway, Fly, and any other Docker host work the same way. They inject `PORT`; the image already binds `0.0.0.0:$PORT`.

Ask timeouts can exceed 30s (free models). Raise the platform request timeout if Ask is cut off.

Copy `.env.example` to `.env` to point at Neo4j Aura (`neo4j+s://…`) or a local instance that is not `bolt://localhost:7687`. Aura credentials use `NEO4J_USERNAME`. The password stays in `.env`; that file is gitignored.

Optional wording model, any OpenAI-compatible endpoint:

```bash
DEVMIND_LLM_BASE_URL=http://localhost:11434/v1
DEVMIND_LLM_API_KEY=ollama
DEVMIND_LLM_MODEL=llama3.1
```

Leave these unset and the briefing is still produced from the graph.

## Try the billing sample

In the UI, choose **Load billing sample**. Then ask:

- What does `calculate_tax` do?
- Why are amounts stored in integer cents?
- Why is `apply_payment` safe to retry?

The sample contains integer-cent and floating-point decisions, a resolved webhook issue, the `IntegrityError` it caused, the solution, and pull request 38.

**Ingest DevMind** loads this repository, including the ADRs under `docs/adr` and `.devmind/memory.json`.

You can also ingest any local project:

```bash
python -m app.ingest.cli --path ..\examples\billing-service --name "Billing Service"
```

The API reads local directories. It listens on `127.0.0.1` by default. Ingest refuses more than 8,000 files.

## Project memory you add later

ADRs live in `docs/adr/` or `docs/decisions/`. A useful record looks like this:

```markdown
# Store money as integer cents

Status: accepted
Date: 2024-02-12
Deciders: Lena Ortiz
Supersedes: 0000-use-floating-point-dollars

## Context
Invoice totals drifted.

## Decision
All monetary amounts are integer cents.

## Consequences
Format currency at the edge.

Affects: app/pricing.py, calculate_tax
```

Issues, errors, solutions, and pull requests live in `.devmind/memory.json`. See `examples/billing-service/.devmind/memory.json`.

The **Record a decision** form writes a `Decision` node immediately. The next why-question can find it by the words in the title and rationale.

## Tests

From `backend`:

```bash
pytest
```

The unit tests cover parsing, the billing-service graph document, what/why classification, and the rule that a model cannot invent a rationale. They do not require Neo4j.
