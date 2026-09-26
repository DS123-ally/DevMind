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

1. Intent detection (callers, technologies, bug history, how-fixed, why-technology, overview).
2. Neo4j retrieval of a bounded subgraph — not a chat log.
3. Code neighborhood (files, functions, imports, calls).
4. Context builder from those relationships.
5. Optional LLM rephrase, grounded in graph facts.
6. Citations, WHY path (`Technology → Decision → Issue → Solution → PR`).
7. Conversation stored in Neo4j. Phrases like “remember that we decided…” extract a Decision node.

Open `http://127.0.0.1:5173` (Vite) or `http://127.0.0.1:3000` (Next.js + React Flow). Connect a GitHub repo with the GitHub URL field (`GITHUB_TOKEN` in `.env` for private repos). Zip upload: `POST /api/ingest/upload`.

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
