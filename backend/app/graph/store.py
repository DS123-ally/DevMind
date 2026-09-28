"""Neo4j is the system of record for project memory. Every write and read goes through this store."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from neo4j import Driver, GraphDatabase
from neo4j.exceptions import Neo4jError

from app.ids import node_id
from app.ingest.model import IngestDocument
from app.graph.crud import GraphCrud
from app.graph.cypher import GRAPH_DIR, load_schema, named_queries, statements

SCHEMA = load_schema()
QUERIES = named_queries()


class GraphStore:
    def __init__(self, uri: str, user: str, password: str, database: str) -> None:
        self.uri = uri
        self.database = database
        self.driver: Driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self) -> None:
        self.driver.close()

    @property
    def crud(self) -> GraphCrud:
        return GraphCrud(self.driver, self.database)

    def verify(self) -> None:
        self.driver.verify_connectivity()

    def ensure_schema(self) -> None:
        with self.driver.session(database=self.database) as session:
            for statement in SCHEMA:
                session.run(statement).consume()

    def seed_graph(self, repo_id: str) -> dict:
        return self.crud.seed(statements(GRAPH_DIR / "seed.cypher"), repo_id)

    def list_projects(self) -> list[dict]:
        query = """
        MATCH (r:Repository)
        OPTIONAL MATCH (f:File {repoId: r.id})
        RETURN r.id AS id, r.name AS name, r.path AS path, r.summary AS summary,
               r.updatedAt AS updatedAt, r.githubUrl AS githubUrl, count(f) AS files
        ORDER BY r.updatedAt DESC
        """
        with self.driver.session(database=self.database) as session:
            return [dict(row) for row in session.run(query)]

    def get_project(self, repo_id: str) -> dict | None:
        query = """
        MATCH (r:Repository {id: $repoId})
        OPTIONAL MATCH (r)-[:USES]->(t:Technology)
        WITH r, t ORDER BY t.name
        WITH r, collect(DISTINCT {name: t.name, category: t.category}) AS technologies
        OPTIONAL MATCH (d:Decision {repoId: $repoId})
        WITH r, technologies, d ORDER BY d.date DESC
        RETURN properties(r) AS repository, technologies,
               [item IN collect(DISTINCT {title: d.title, status: d.status, date: d.date, id: d.id}) WHERE item.title IS NOT NULL] AS decisions
        """
        with self.driver.session(database=self.database) as session:
            record = session.run(query, repoId=repo_id).single()
        if record is None:
            return None
        technologies = [item for item in record["technologies"] if item.get("name")]
        return {
            "repository": record["repository"],
            "technologies": technologies,
            "decisions": record["decisions"][:12],
        }

    def inventory(self, repo_id: str) -> dict:
        counts_query = """
        MATCH (n {repoId: $repoId})
        RETURN labels(n)[0] AS label, count(n) AS count
        ORDER BY label
        """
        rel_query = """
        MATCH (a {repoId: $repoId})-[r]->()
        RETURN type(r) AS type, count(r) AS count
        ORDER BY count DESC
        """
        with self.driver.session(database=self.database) as session:
            counts = {row["label"]: row["count"] for row in session.run(counts_query, repoId=repo_id)}
            relationships = {row["type"]: row["count"] for row in session.run(rel_query, repoId=repo_id)}
        return {"counts": counts, "relationships": relationships}

    def tree(self, repo_id: str) -> dict | None:
        query = """
        MATCH (r:Repository {id: $repoId})
        OPTIONAL MATCH (d:Directory {repoId: $repoId})
        WITH r, collect(DISTINCT {path: d.path, name: d.name}) AS directories
        OPTIONAL MATCH (f:File {repoId: $repoId})
        RETURN r.name AS name,
               directories,
               collect(DISTINCT {path: f.path, name: f.name, language: f.language}) AS files
        """
        with self.driver.session(database=self.database) as session:
            record = session.run(query, repoId=repo_id).single()
        if record is None:
            return None
        return build_tree(record["name"], record["directories"], record["files"])

    def search(self, repo_id: str, tokens: list[str], lucene: str) -> list[dict]:
        found: dict[str, dict] = {}
        exact = """
        MATCH (n {repoId: $repoId})
        WHERE toLower(coalesce(n.name, '')) IN $tokens
           OR toLower(coalesce(n.title, '')) IN $tokens
           OR toLower(coalesce(n.key, '')) IN $tokens
        RETURN n.id AS id, labels(n) AS labels,
               coalesce(n.name, n.title, n.key, n.path, '') AS name
        LIMIT 25
        """
        fulltext = """
        CALL db.index.fulltext.queryNodes('devmind_search', $q) YIELD node, score
        WHERE node.repoId = $repoId
        RETURN node.id AS id, labels(node) AS labels,
               coalesce(node.name, node.title, node.key, node.path, '') AS name,
               score
        LIMIT 20
        """
        contains = """
        UNWIND $tokens AS token
        MATCH (n {repoId: $repoId})
        WHERE toLower(coalesce(n.name, '')) CONTAINS token
           OR toLower(coalesce(n.title, '')) CONTAINS token
           OR toLower(coalesce(n.qualifiedName, '')) CONTAINS token
           OR toLower(coalesce(n.path, '')) CONTAINS token
           OR toLower(coalesce(n.rationale, '')) CONTAINS token
           OR toLower(coalesce(n.message, '')) CONTAINS token
           OR toLower(coalesce(n.summary, '')) CONTAINS token
           OR toLower(coalesce(n.description, '')) CONTAINS token
           OR toLower(coalesce(n.signature, '')) CONTAINS token
           OR toLower(coalesce(n.key, '')) CONTAINS token
        WITH n, count(token) AS score
        RETURN n.id AS id, labels(n) AS labels,
               coalesce(n.name, n.title, n.key, n.path, '') AS name,
               score
        LIMIT 20
        """
        with self.driver.session(database=self.database) as session:
            if tokens:
                for row in session.run(exact, repoId=repo_id, tokens=tokens):
                    _accumulate(found, row, 12)
            if lucene:
                try:
                    for row in session.run(fulltext, repoId=repo_id, q=lucene):
                        _accumulate(found, row, float(row["score"]))
                except Neo4jError:
                    for row in session.run(contains, repoId=repo_id, tokens=tokens):
                        _accumulate(found, row, float(row["score"]))
            if not found and tokens:
                for row in session.run(contains, repoId=repo_id, tokens=tokens):
                    _accumulate(found, row, float(row["score"]))
        ranked = sorted(found.values(), key=lambda item: item["score"], reverse=True)
        return ranked[:12]

    def overview(self, repo_id: str) -> dict:
        repo_query = "MATCH (r:Repository {id: $repoId}) RETURN properties(r) AS props"
        tech_query = """
        MATCH (:Repository {id: $repoId})-[:USES]->(t:Technology)
        RETURN t.name AS name, t.category AS category
        ORDER BY t.name
        """
        decision_query = """
        MATCH (d:Decision {repoId: $repoId})
        OPTIONAL MATCH (d)-[:DECIDED_BY]->(dev:Developer)
        OPTIONAL MATCH (d)-[:SUPERSEDES]->(old:Decision)
        OPTIONAL MATCH (d)-[:ABOUT]->(n)
        WITH d,
             collect(DISTINCT dev.name) AS deciders,
             collect(DISTINCT old.title) AS supersedes,
             collect(DISTINCT coalesce(n.qualifiedName, n.path, n.title, n.name)) AS about
        ORDER BY d.status, d.date
        LIMIT 8
        RETURN properties(d) AS decision, deciders, supersedes, about
        """
        file_query = """
        MATCH (f:File {repoId: $repoId})
        WHERE f.name IN ['README.md', 'readme.md', 'api.py', 'main.py', 'app.py', 'index.ts', 'index.tsx']
           OR f.docstring IS NOT NULL
        WITH f ORDER BY CASE WHEN f.docstring IS NULL THEN 1 ELSE 0 END, f.path
        LIMIT 6
        OPTIONAL MATCH (f)-[:DEFINES]->(s)
        RETURN properties(f) AS file, collect(DISTINCT s.name)[..8] AS defines
        """
        with self.driver.session(database=self.database) as session:
            repo = session.run(repo_query, repoId=repo_id).single()
            technologies = [dict(row) for row in session.run(tech_query, repoId=repo_id)]
            decisions = [dict(row) for row in session.run(decision_query, repoId=repo_id)]
            files = [dict(row) for row in session.run(file_query, repoId=repo_id)]
            conversations = [
                dict(row)
                for row in session.run(
                    """
                    MATCH (c:Conversation {repoId: $repoId})
                    RETURN c.question AS question, c.headline AS headline, c.createdAt AS createdAt
                    ORDER BY c.createdAt DESC
                    LIMIT 3
                    """,
                    repoId=repo_id,
                )
            ]
        return {
            "repository": repo["props"] if repo else {},
            "technologies": technologies,
            "decisions": decisions,
            "files": files,
            "nodes": [],
            "calls": [],
            "issues": [],
            "errors": [],
            "pullRequests": [],
            "conversations": conversations,
            "developers": [],
            "imports": [],
            "extends": [],
            "uses": [{"owner": "repository", "technology": item["name"]} for item in technologies],
            "defines": [],
        }

    def neighborhood(self, repo_id: str, seed_ids: list[str]) -> dict:
        nodes_query = """
        MATCH (n {repoId: $repoId})
        WHERE n.id IN $ids
        RETURN n.id AS id, labels(n) AS labels, properties(n) AS props
        """
        calls_query = """
        MATCH (a:Function {repoId: $repoId})-[:CALLS]->(b:Function {repoId: $repoId})
        WHERE a.id IN $ids OR b.id IN $ids
        RETURN a.id AS fromId, a.qualifiedName AS fromName, b.id AS toId, b.qualifiedName AS toName
        LIMIT 80
        """
        decisions_query = """
        MATCH (d:Decision {repoId: $repoId})-[:ABOUT]->(n)
        WHERE n.id IN $ids OR d.id IN $ids
        OPTIONAL MATCH (d)-[:DECIDED_BY]->(dev:Developer)
        OPTIONAL MATCH (d)-[:SUPERSEDES]->(old:Decision)
        OPTIONAL MATCH (d)-[:ABOUT]->(about)
        RETURN properties(d) AS decision,
               collect(DISTINCT dev.name) AS deciders,
               collect(DISTINCT old.title) AS supersedes,
               collect(DISTINCT coalesce(about.qualifiedName, about.path, about.title, about.name)) AS about
        """
        issues_query = """
        MATCH (i:Issue {repoId: $repoId})-[:AFFECTS]->(n)
        WHERE n.id IN $ids OR i.id IN $ids
        OPTIONAL MATCH (s:Solution)-[:RESOLVES]->(i)
        OPTIONAL MATCH (i)-[:AFFECTS]->(affected)
        RETURN properties(i) AS issue,
               collect(DISTINCT coalesce(affected.qualifiedName, affected.path, affected.title, affected.name)) AS affects,
               collect(DISTINCT s.summary) AS solutions
        """
        errors_query = """
        MATCH (e:Error {repoId: $repoId})-[:OCCURS_IN]->(n)
        WHERE n.id IN $ids OR e.id IN $ids
        OPTIONAL MATCH (s:Solution)-[:RESOLVES]->(e)
        OPTIONAL MATCH (e)-[:OCCURS_IN]->(place)
        RETURN properties(e) AS error,
               collect(DISTINCT coalesce(place.qualifiedName, place.path, place.title, place.name)) AS occursIn,
               collect(DISTINCT s.summary) AS solutions
        """
        pr_query = """
        MATCH (pr:PullRequest {repoId: $repoId})-[:CHANGES]->(f:File)
        WHERE f.id IN $ids OR pr.id IN $ids
        OPTIONAL MATCH (pr)-[:AUTHORED_BY]->(dev:Developer)
        OPTIONAL MATCH (pr)-[:CHANGES]->(changed:File)
        RETURN properties(pr) AS pullRequest,
               collect(DISTINCT changed.path) AS files,
               collect(DISTINCT dev.name) AS authors
        """
        conversation_query = """
        MATCH (c:Conversation {repoId: $repoId})-[:ABOUT]->(n)
        WHERE n.id IN $ids
        WITH DISTINCT c
        RETURN c.question AS question, c.headline AS headline, c.createdAt AS createdAt
        ORDER BY c.createdAt DESC
        LIMIT 5
        """
        uses_query = """
        MATCH (f:File {repoId: $repoId})-[:USES]->(t:Technology)
        WHERE f.id IN $ids OR t.id IN $ids
        RETURN f.path AS owner, t.name AS technology
        LIMIT 40
        """
        imports_query = """
        MATCH (a:File {repoId: $repoId})-[:IMPORTS]->(b:File {repoId: $repoId})
        WHERE a.id IN $ids OR b.id IN $ids
        RETURN a.path AS fromPath, b.path AS toPath
        LIMIT 40
        """
        extends_query = """
        MATCH (a:Class {repoId: $repoId})-[:EXTENDS]->(b:Class {repoId: $repoId})
        WHERE a.id IN $ids OR b.id IN $ids
        RETURN a.name AS fromName, b.name AS toName, a.qualifiedName AS fromQual, b.qualifiedName AS toQual
        """
        developers_query = """
        MATCH (dev:Developer {repoId: $repoId})-[r:AUTHORED]->(f:File)
        WHERE f.id IN $ids
        RETURN dev.name AS name, f.path AS path, r.commits AS commits
        LIMIT 20
        """
        with self.driver.session(database=self.database) as session:
            ids = _expand_ids(session, repo_id, seed_ids)
            params = {"repoId": repo_id, "ids": ids}
            repo = session.run("MATCH (r:Repository {id: $repoId}) RETURN properties(r) AS props", repoId=repo_id).single()
            return {
                "repository": repo["props"] if repo else {},
                "ids": ids,
                "nodes": [dict(row) for row in session.run(nodes_query, **params)],
                "calls": [dict(row) for row in session.run(calls_query, **params)],
                "decisions": [dict(row) for row in session.run(decisions_query, **params)],
                "issues": [dict(row) for row in session.run(issues_query, **params)],
                "errors": [dict(row) for row in session.run(errors_query, **params)],
                "pullRequests": [dict(row) for row in session.run(pr_query, **params)],
                "conversations": [dict(row) for row in session.run(conversation_query, **params)],
                "uses": [dict(row) for row in session.run(uses_query, **params)],
                "imports": [dict(row) for row in session.run(imports_query, **params)],
                "extends": [dict(row) for row in session.run(extends_query, **params)],
                "developers": [dict(row) for row in session.run(developers_query, **params)],
                "technologies": [],
                "files": [],
                "defines": [],
            }

    def apply(self, doc: IngestDocument) -> dict:
        file_rows = [_file_row(item) for item in doc.files]
        class_rows = []
        function_rows = []
        class_ids = {(item.file_id, item.name): item.id for item in doc.symbols if item.kind == "class"}
        for symbol in doc.symbols:
            if symbol.kind == "class":
                class_rows.append(_symbol_row(symbol))
            else:
                row = _symbol_row(symbol)
                if symbol.class_name:
                    row["classId"] = class_ids.get((symbol.file_id, symbol.class_name))
                function_rows.append(row)

        with self.driver.session(database=self.database) as session:
            previous = {
                row["id"]: row["sha"]
                for row in session.run(
                    "MATCH (f:File {repoId: $repoId}) RETURN f.id AS id, f.sha256 AS sha",
                    repoId=doc.repo_id,
                )
            }
            changed = sum(1 for item in doc.files if previous.get(item.id) != item.sha256)
            with session.begin_transaction() as tx:
                _write_structure(tx, doc, file_rows, class_rows, function_rows)
                _write_memory(tx, doc)
                tx.run(
                    """
                    MATCH (d:Developer {repoId: $repoId})
                    WHERE NOT (d)--()
                    DELETE d
                    """,
                    repoId=doc.repo_id,
                )
                tx.commit()
        return {
            "repositoryId": doc.repo_id,
            "name": doc.name,
            "path": doc.path,
            "files": len(doc.files),
            "directories": len(doc.directories),
            "symbols": len(doc.symbols),
            "decisions": len(doc.decisions),
            "issues": len(doc.issues),
            "errors": len(doc.errors),
            "solutions": len(doc.solutions),
            "pullRequests": len(doc.pull_requests),
            "technologies": [item.name for item in doc.technologies],
            "changedFiles": changed,
            "warnings": doc.warnings,
        }

    def add_decision(
        self,
        repo_id: str,
        title: str,
        rationale: str,
        status: str,
        about_ids: list[str],
        decider: str | None,
    ) -> dict:
        slug = _slug(title) or uuid.uuid4().hex[:8]
        decision_id = node_id(repo_id, "decision", slug)
        decider_id = node_id(repo_id, "developer", decider.strip().lower()) if decider else None
        now = _now()
        query = """
        MATCH (r:Repository {id: $repoId})
        MERGE (d:Decision {id: $id})
        SET d.repoId = $repoId, d.slug = $slug, d.title = $title, d.rationale = $rationale,
            d.status = $status, d.source = 'user', d.date = $now
        MERGE (d)-[:ABOUT]->(r)
        WITH d
        FOREACH (ignore IN CASE WHEN $deciderId IS NULL THEN [] ELSE [1] END |
          MERGE (dev:Developer {id: $deciderId})
          SET dev.repoId = $repoId, dev.name = $decider, dev.email = ''
          MERGE (d)-[:DECIDED_BY]->(dev)
          MERGE (dev)-[:WORKS_ON]->(:Repository {id: $repoId})
        )
        WITH d
        OPTIONAL MATCH (n {repoId: $repoId})
        WHERE n.id IN $aboutIds
        WITH d, collect(n) AS nodes
        FOREACH (node IN nodes | MERGE (d)-[:ABOUT]->(node))
        RETURN d.id AS id, d.title AS title, d.status AS status
        """
        with self.driver.session(database=self.database) as session:
            record = session.run(
                query,
                repoId=repo_id,
                id=decision_id,
                slug=slug,
                title=title,
                rationale=rationale,
                status=status,
                now=now,
                deciderId=decider_id,
                decider=decider or "",
                aboutIds=about_ids,
            ).single()
        if record is None:
            raise LookupError("Repository not found")
        return dict(record)

    def add_issue(
        self,
        repo_id: str,
        key: str,
        title: str,
        description: str,
        status: str,
        about_ids: list[str],
        resolution: str | None,
    ) -> dict:
        issue_id = node_id(repo_id, "issue", key)
        solution_id = node_id(repo_id, "solution", _slug(resolution) or key) if resolution else None
        query = """
        MATCH (r:Repository {id: $repoId})
        MERGE (i:Issue {id: $id})
        SET i.repoId = $repoId, i.key = $key, i.title = $title, i.description = $description,
            i.status = $status, i.source = 'user'
        MERGE (i)-[:AFFECTS]->(r)
        WITH i
        OPTIONAL MATCH (n {repoId: $repoId})
        WHERE n.id IN $aboutIds
        WITH i, collect(n) AS nodes
        FOREACH (node IN nodes | MERGE (i)-[:AFFECTS]->(node))
        FOREACH (ignore IN CASE WHEN $solutionId IS NULL THEN [] ELSE [1] END |
          MERGE (s:Solution {id: $solutionId})
          SET s.repoId = $repoId, s.key = $solutionKey, s.summary = $resolution, s.source = 'user'
          MERGE (s)-[:RESOLVES]->(i)
        )
        RETURN i.id AS id, i.key AS key, i.title AS title, i.status AS status
        """
        with self.driver.session(database=self.database) as session:
            record = session.run(
                query,
                repoId=repo_id,
                id=issue_id,
                key=key,
                title=title,
                description=description,
                status=status,
                aboutIds=about_ids,
                solutionId=solution_id,
                solutionKey=_slug(resolution or "") or key,
                resolution=resolution or "",
            ).single()
        if record is None:
            raise LookupError("Repository not found")
        return dict(record)

    def add_solution(
        self,
        repo_id: str,
        summary: str,
        issue_key: str | None,
        about_ids: list[str],
    ) -> dict:
        key = _slug(summary) or uuid.uuid4().hex[:8]
        solution_id = node_id(repo_id, "solution", key)
        query = """
        MATCH (r:Repository {id: $repoId})
        MERGE (s:Solution {id: $id})
        SET s.repoId = $repoId, s.key = $key, s.summary = $summary, s.source = 'user'
        WITH s
        OPTIONAL MATCH (i:Issue {repoId: $repoId})
        WHERE $issueKey <> '' AND toUpper(i.key) = toUpper($issueKey)
        FOREACH (issue IN CASE WHEN i IS NULL THEN [] ELSE [i] END |
          MERGE (s)-[:RESOLVES]->(issue)
        )
        WITH s
        OPTIONAL MATCH (i:Issue {repoId: $repoId})
        WHERE $issueKey <> '' AND toUpper(i.key) = toUpper($issueKey)
        FOREACH (issue IN CASE WHEN i IS NULL THEN [] ELSE [i] END |
          MERGE (s)-[:RESOLVES]->(issue)
        )
        RETURN s.id AS id, s.key AS key, s.summary AS summary
        """
        with self.driver.session(database=self.database) as session:
            record = session.run(
                query,
                repoId=repo_id,
                id=solution_id,
                key=key,
                summary=summary,
                issueKey=issue_key or "",
                aboutIds=about_ids,
            ).single()
        if record is None:
            raise LookupError("Repository not found")
        return dict(record)

    def recent_conversations(self, repo_id: str, limit: int = 5) -> list[dict]:
        query = """
        MATCH (c:Conversation {repoId: $repoId})
        RETURN c.question AS question, c.headline AS headline, c.createdAt AS createdAt
        ORDER BY c.createdAt DESC
        LIMIT $limit
        """
        with self.driver.session(database=self.database) as session:
            rows = [dict(row) for row in session.run(query, repoId=repo_id, limit=limit)]
        for row in rows:
            if row.get("createdAt") is not None:
                row["createdAt"] = str(row["createdAt"])
        return rows

    def save_briefing(self, repo_id: str, briefing: dict, about_ids: list[str]) -> str:
        conversation_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        assistant_id = str(uuid.uuid4())
        created = _now()
        query = """
        MATCH (r:Repository {id: $repoId})
        CREATE (c:Conversation {
          id: $id, repoId: $repoId, question: $question, mode: $mode, headline: $headline,
          answer: $answer, whatJson: $whatJson, whyJson: $whyJson, gapsJson: $gapsJson,
          evidenceJson: $evidenceJson, voice: $voice, createdAt: $createdAt
        })
        CREATE (q:Message {id: $userId, repoId: $repoId, role: 'user', content: $question, createdAt: $createdAt})
        CREATE (a:Message {id: $assistantId, repoId: $repoId, role: 'assistant', content: $answer, createdAt: $createdAt})
        MERGE (c)-[:HAS_MESSAGE {order: 0}]->(q)
        MERGE (c)-[:HAS_MESSAGE {order: 1}]->(a)
        MERGE (c)-[:IN_REPOSITORY]->(r)
        WITH c
        OPTIONAL MATCH (n {repoId: $repoId})
        WHERE n.id IN $aboutIds
        WITH c, collect(n) AS nodes
        FOREACH (node IN nodes | MERGE (c)-[:ABOUT]->(node))
        RETURN c.id AS id
        """
        answer = "\n".join(briefing["what"] + briefing["why"])
        with self.driver.session(database=self.database) as session:
            record = session.run(
                query,
                repoId=repo_id,
                id=conversation_id,
                question=briefing["question"],
                mode=briefing["mode"],
                headline=briefing["headline"],
                answer=answer[:8000],
                whatJson=json.dumps(briefing["what"]),
                whyJson=json.dumps(briefing["why"]),
                gapsJson=json.dumps(briefing["gaps"]),
                evidenceJson=json.dumps(briefing["evidence"]),
                voice=briefing["voice"],
                createdAt=created,
                userId=user_id,
                assistantId=assistant_id,
                aboutIds=about_ids[:12],
            ).single()
        return record["id"] if record else conversation_id

    def list_briefings(self, repo_id: str) -> list[dict]:
        query = """
        MATCH (c:Conversation {repoId: $repoId})
        RETURN c.id AS id, c.question AS question, c.mode AS mode, c.headline AS headline,
               c.whatJson AS whatJson, c.whyJson AS whyJson, c.gapsJson AS gapsJson,
               c.evidenceJson AS evidenceJson, c.voice AS voice, c.createdAt AS createdAt
        ORDER BY c.createdAt DESC
        LIMIT 30
        """
        with self.driver.session(database=self.database) as session:
            rows = [dict(row) for row in session.run(query, repoId=repo_id)]
        briefings = []
        for row in rows:
            briefings.append(
                {
                    "id": row["id"],
                    "question": row["question"],
                    "mode": row["mode"],
                    "headline": row["headline"],
                    "what": _load_json(row.get("whatJson"), []),
                    "why": _load_json(row.get("whyJson"), []),
                    "gaps": _load_json(row.get("gapsJson"), []),
                    "evidence": _load_json(row.get("evidenceJson"), []),
                    "voice": row.get("voice") or "graph",
                    "createdAt": str(row.get("createdAt") or ""),
                }
            )
        return briefings

    def subgraph(self, repo_id: str, seed_ids: list[str] | None = None) -> dict:
        query = """
        MATCH (n {repoId: $repoId})
        WHERE $seeds IS NULL OR size($seeds) = 0 OR n.id IN $seeds
           OR n:Technology OR n:Decision OR n:Issue OR n:Solution OR n:PullRequest OR n:Error
        WITH n LIMIT 90
        OPTIONAL MATCH (n)-[r]->(m {repoId: $repoId})
        RETURN collect(DISTINCT {id: n.id, labels: labels(n), name: coalesce(n.name, n.title, n.key, n.path, n.qualifiedName, '')}) AS nodes,
               collect(DISTINCT CASE WHEN m IS NULL THEN null ELSE {source: n.id, target: m.id, type: type(r)} END) AS edges
        """
        with self.driver.session(database=self.database) as session:
            record = session.run(query, repoId=repo_id, seeds=seed_ids or []).single()
        nodes = [item for item in (record["nodes"] if record else []) if item and item.get("id")]
        edges = [item for item in (record["edges"] if record else []) if item and item.get("source")]
        return {"nodes": nodes[:80], "edges": edges[:140]}

    def why_path(self, repo_id: str, tokens: list[str]) -> list[dict]:
        query = """
        MATCH (t:Technology {repoId: $repoId})
        OPTIONAL MATCH (d:Decision {repoId: $repoId})-[:CHOOSES]->(t)
        OPTIONAL MATCH (s:Solution {repoId: $repoId})-[:INFORMS]->(d)
        OPTIONAL MATCH (s)-[:RESOLVES]->(i:Issue)
        OPTIONAL MATCH (i)-[:CAUSED]->(e:Error)
        OPTIONAL MATCH (pr:PullRequest)-[:CLOSES]->(i)
        WITH t, d, s, i, e, pr
        WHERE d IS NOT NULL OR i IS NOT NULL
        RETURN t.name AS technology, d.title AS decision, d.rationale AS rationale,
               i.key AS issue, i.title AS issueTitle, e.type AS error,
               s.summary AS solution, pr.number AS pull, pr.title AS pullTitle
        LIMIT 8
        """
        with self.driver.session(database=self.database) as session:
            rows = [dict(row) for row in session.run(query, repoId=repo_id)]
        if tokens:
            lowered = [token.lower() for token in tokens]
            ranked = []
            for row in rows:
                blob = " ".join(str(value or "") for value in row.values()).lower()
                score = sum(1 for token in lowered if token in blob)
                ranked.append((score, row))
            ranked.sort(key=lambda item: item[0], reverse=True)
            rows = [row for score, row in ranked if score] or rows
        path = []
        for row in rows[:3]:
            if row.get("technology"):
                path.append({"kind": "Technology", "name": row["technology"], "relationship": "CHOOSES"})
            if row.get("decision"):
                path.append({"kind": "Decision", "name": row["decision"], "relationship": "INFORMS", "note": row.get("rationale")})
            if row.get("issue"):
                path.append({"kind": "Issue", "name": f"{row['issue']}: {row.get('issueTitle') or ''}".strip(), "relationship": "CAUSED"})
            if row.get("error"):
                path.append({"kind": "Error", "name": row["error"], "relationship": "RESOLVES"})
            if row.get("solution"):
                path.append({"kind": "Solution", "name": row["solution"], "relationship": "CLOSES"})
            if row.get("pull"):
                path.append({"kind": "PullRequest", "name": f"#{row['pull']} {row.get('pullTitle') or ''}".strip(), "relationship": ""})
        seen = set()
        unique = []
        for item in path:
            key = (item["kind"], item["name"])
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)
        return unique

    def file_record(self, repo_id: str, path: str) -> dict | None:
        query = """
        MATCH (r:Repository {id: $repoId})
        MATCH (f:File {repoId: $repoId, path: $path})
        OPTIONAL MATCH (f)-[:DEFINES]->(s)
        RETURN r.path AS root, properties(f) AS file, collect(DISTINCT {name: s.name, kind: labels(s)[0], line: s.line, signature: s.signature}) AS symbols
        """
        with self.driver.session(database=self.database) as session:
            record = session.run(query, repoId=repo_id, path=path).single()
        return dict(record) if record else None

    def memory_panel(self, repo_id: str) -> dict:
        with self.driver.session(database=self.database) as session:
            decisions = [
                dict(row)
                for row in session.run(
                    """
                    MATCH (d:Decision {repoId: $repoId})
                    OPTIONAL MATCH (d)-[:CHOOSES]->(t:Technology)
                    OPTIONAL MATCH (s:Solution)-[:INFORMS]->(d)
                    WITH d, collect(DISTINCT t.name) AS technologies, collect(DISTINCT s.summary) AS solutions
                    ORDER BY d.date DESC
                    RETURN d.id AS id, d.title AS title, d.status AS status, d.rationale AS rationale,
                           d.source AS source, technologies, solutions
                    """,
                    repoId=repo_id,
                )
            ]
            issues = [
                dict(row)
                for row in session.run(
                    """
                    MATCH (i:Issue {repoId: $repoId})
                    OPTIONAL MATCH (i)-[:CAUSED]->(e:Error)
                    OPTIONAL MATCH (sol:Solution)-[:RESOLVES]->(i)
                    OPTIONAL MATCH (pr:PullRequest)-[:CLOSES]->(i)
                    RETURN i.id AS id, i.key AS key, i.title AS title, i.status AS status, i.source AS source,
                           collect(DISTINCT e.type) AS errors, collect(DISTINCT sol.summary) AS solutions,
                           collect(DISTINCT pr.number) AS pulls
                    """,
                    repoId=repo_id,
                )
            ]
            conversations = [
                dict(row)
                for row in session.run(
                    """
                    MATCH (c:Conversation {repoId: $repoId})
                    RETURN c.id AS id, c.question AS question, c.headline AS headline, c.mode AS mode, c.createdAt AS createdAt
                    ORDER BY c.createdAt DESC LIMIT 20
                    """,
                    repoId=repo_id,
                )
            ]
        return {"decisions": decisions, "issues": issues, "conversations": conversations}

    def sample_functions(self, repo_id: str, limit: int = 8) -> list[str]:
        query = """
        MATCH (f:Function {repoId: $repoId})
        WHERE f.name IS NOT NULL AND size(f.name) > 3 AND NOT f.name STARTS WITH '_'
        OPTIONAL MATCH (caller:Function {repoId: $repoId})-[:CALLS]->(f)
        WITH f.name AS name, count(caller) AS callers
        ORDER BY callers DESC, size(name) DESC, name
        WITH name, max(callers) AS callers
        ORDER BY callers DESC, size(name) DESC, name
        RETURN name
        LIMIT $limit
        """
        with self.driver.session(database=self.database) as session:
            return [row["name"] for row in session.run(query, repoId=repo_id, limit=limit) if row["name"]]


def build_tree(name: str, directories: list[dict], files: list[dict]) -> dict:
    root = {"name": name or "repository", "path": ".", "type": "dir", "children": []}
    nodes = {".": root}
    for directory in sorted(directories, key=lambda item: item.get("path") or ""):
        path = directory.get("path")
        if not path or path == ".":
            continue
        node = {"name": directory.get("name") or path, "path": path, "type": "dir", "children": []}
        nodes[path] = node
        parent = path.rsplit("/", 1)[0] if "/" in path else "."
        nodes.setdefault(parent, root)["children"].append(node)
    for file in sorted(files, key=lambda item: item.get("path") or ""):
        path = file.get("path")
        if not path:
            continue
        parent = path.rsplit("/", 1)[0] if "/" in path else "."
        nodes.setdefault(parent, root)["children"].append(
            {
                "name": file.get("name") or path,
                "path": path,
                "type": "file",
                "language": file.get("language"),
                "children": [],
            }
        )
    _sort_tree(root)
    return root


def _write_structure(tx, doc: IngestDocument, file_rows: list[dict], class_rows: list[dict], function_rows: list[dict]) -> None:
    repo_id = doc.repo_id
    tx.run(
        """
        MERGE (r:Repository {id: $repoId})
        SET r.name = $name, r.path = $path, r.summary = $summary, r.repoId = $repoId, r.updatedAt = $now,
            r.githubUrl = $githubUrl, r.defaultBranch = $defaultBranch, r.languagesJson = $languagesJson,
            r.githubOwner = $githubOwner, r.githubName = $githubName, r.githubFullName = $githubFullName,
            r.githubStars = $githubStars, r.githubForks = $githubForks, r.githubWatchers = $githubWatchers,
            r.githubOpenIssues = $githubOpenIssues, r.githubLanguage = $githubLanguage,
            r.githubLicense = $githubLicense, r.githubTopicsJson = $githubTopicsJson,
            r.githubVisibility = $githubVisibility, r.githubHomepage = $githubHomepage,
            r.githubPushedAt = $githubPushedAt, r.githubArchived = $githubArchived
        """,
        repoId=repo_id,
        name=doc.name,
        path=doc.path,
        summary=doc.summary,
        now=_now(),
        githubUrl=doc.github_url,
        defaultBranch=doc.default_branch,
        languagesJson=json.dumps(doc.languages),
        githubOwner=(doc.github or {}).get("owner"),
        githubName=(doc.github or {}).get("name"),
        githubFullName=(doc.github or {}).get("fullName"),
        githubStars=(doc.github or {}).get("stars"),
        githubForks=(doc.github or {}).get("forks"),
        githubWatchers=(doc.github or {}).get("watchers"),
        githubOpenIssues=(doc.github or {}).get("openIssues"),
        githubLanguage=(doc.github or {}).get("language"),
        githubLicense=(doc.github or {}).get("license"),
        githubTopicsJson=json.dumps((doc.github or {}).get("topics") or []),
        githubVisibility=(doc.github or {}).get("visibility"),
        githubHomepage=(doc.github or {}).get("homepage"),
        githubPushedAt=(doc.github or {}).get("pushedAt"),
        githubArchived=(doc.github or {}).get("archived"),
    )
    tx.run(
        """
        MATCH (f:File {repoId: $repoId})
        WHERE NOT f.id IN $keep
        OPTIONAL MATCH (f)-[:DEFINES]->(s)
        DETACH DELETE s
        WITH DISTINCT f
        DETACH DELETE f
        """,
        repoId=repo_id,
        keep=[item.id for item in doc.files],
    )
    tx.run(
        """
        MATCH (n {repoId: $repoId})
        WHERE n:Class OR n:Function
        DETACH DELETE n
        """,
        repoId=repo_id,
    )
    tx.run(
        """
        MATCH (d:Directory {repoId: $repoId})
        WHERE NOT d.id IN $keep
        DETACH DELETE d
        """,
        repoId=repo_id,
        keep=[item.id for item in doc.directories],
    )
    tx.run("MATCH (t:Technology {repoId: $repoId}) DETACH DELETE t", repoId=repo_id)
    for batch in _chunks([_dir_row(item) for item in doc.directories]):
        tx.run(
            """
            UNWIND $rows AS row
            MERGE (d:Directory {id: row.id})
            SET d.repoId = $repoId, d.path = row.path, d.name = row.name
            """,
            repoId=repo_id,
            rows=batch,
        )
    parents = [_dir_row(item) for item in doc.directories if item.parent_id]
    for batch in _chunks(parents):
        tx.run(
            """
            UNWIND $rows AS row
            MATCH (parent:Directory {id: row.parentId})
            MATCH (child:Directory {id: row.id})
            MERGE (parent)-[:CONTAINS]->(child)
            """,
            rows=batch,
        )
    root_ids = [item.id for item in doc.directories if item.path == "."]
    if root_ids:
        tx.run(
            """
            MATCH (r:Repository {id: $repoId})
            MATCH (d:Directory {id: $rootId})
            MERGE (r)-[:CONTAINS]->(d)
            """,
            repoId=repo_id,
            rootId=root_ids[0],
        )
    for batch in _chunks(file_rows):
        tx.run(
            """
            UNWIND $rows AS row
            MERGE (f:File {id: row.id})
            SET f.repoId = $repoId, f.path = row.path, f.name = row.name, f.language = row.language,
                f.loc = row.loc, f.sha256 = row.sha256, f.docstring = row.docstring, f.imports = row.imports
            WITH f, row
            MATCH (d:Directory {id: row.directoryId})
            MERGE (d)-[:CONTAINS]->(f)
            WITH f
            MATCH (r:Repository {id: $repoId})
            MERGE (r)-[:CONTAINS]->(f)
            """,
            repoId=repo_id,
            rows=batch,
        )
    for batch in _chunks(class_rows):
        tx.run(
            """
            UNWIND $rows AS row
            MERGE (c:Class {id: row.id})
            SET c.repoId = $repoId, c.name = row.name, c.qualifiedName = row.qualifiedName,
                c.filePath = row.filePath, c.fileId = row.fileId, c.line = row.line,
                c.docstring = row.docstring, c.bases = row.bases, c.kind = 'class'
            WITH c, row
            MATCH (f:File {id: row.fileId})
            MERGE (f)-[:DEFINES]->(c)
            """,
            repoId=repo_id,
            rows=batch,
        )
    for batch in _chunks(function_rows):
        tx.run(
            """
            UNWIND $rows AS row
            MERGE (fn:Function {id: row.id})
            SET fn.repoId = $repoId, fn.name = row.name, fn.qualifiedName = row.qualifiedName,
                fn.filePath = row.filePath, fn.fileId = row.fileId, fn.line = row.line,
                fn.docstring = row.docstring, fn.signature = row.signature, fn.kind = row.kind,
                fn.className = row.className
            WITH fn, row
            MATCH (f:File {id: row.fileId})
            MERGE (f)-[:DEFINES]->(fn)
            WITH fn, row
            FOREACH (ignore IN CASE WHEN row.classId IS NULL THEN [] ELSE [1] END |
              MERGE (c:Class {id: row.classId})
              MERGE (c)-[:DEFINES]->(fn)
            )
            """,
            repoId=repo_id,
            rows=batch,
        )
    import_rows = [{"from": item.id, "to": target} for item in doc.files for target in item.import_file_ids]
    for batch in _chunks(import_rows):
        tx.run(
            """
            UNWIND $rows AS row
            MATCH (a:File {id: row.from})
            MATCH (b:File {id: row.to})
            MERGE (a)-[:IMPORTS]->(b)
            """,
            rows=batch,
        )
    for batch in _chunks([{"from": source, "to": target} for source, target in doc.calls]):
        tx.run(
            """
            UNWIND $rows AS row
            MATCH (a:Function {id: row.from})
            MATCH (b:Function {id: row.to})
            MERGE (a)-[:CALLS]->(b)
            """,
            rows=batch,
        )
    for batch in _chunks([{"from": source, "to": target} for source, target in doc.extends]):
        tx.run(
            """
            UNWIND $rows AS row
            MATCH (a:Class {id: row.from})
            MATCH (b:Class {id: row.to})
            MERGE (a)-[:EXTENDS]->(b)
            """,
            rows=batch,
        )
    tech_rows = [
        {"id": item.id, "name": item.name, "category": item.category, "manifest": item.manifest}
        for item in doc.technologies
    ]
    for batch in _chunks(tech_rows):
        tx.run(
            """
            UNWIND $rows AS row
            MERGE (t:Technology {id: row.id})
            SET t.repoId = $repoId, t.name = row.name, t.category = row.category, t.manifest = row.manifest
            WITH t
            MATCH (r:Repository {id: $repoId})
            MERGE (r)-[:USES]->(t)
            """,
            repoId=repo_id,
            rows=batch,
        )
    use_rows = [{"tech": item.id, "file": file_id} for item in doc.technologies for file_id in item.file_ids]
    for batch in _chunks(use_rows):
        tx.run(
            """
            UNWIND $rows AS row
            MATCH (t:Technology {id: row.tech})
            MATCH (f:File {id: row.file})
            MERGE (f)-[:USES]->(t)
            """,
            rows=batch,
        )


def _write_memory(tx, doc: IngestDocument) -> None:
    repo_id = doc.repo_id
    for developer in doc.developers:
        tx.run(
            """
            MERGE (d:Developer {id: $id})
            SET d.repoId = $repoId, d.name = $name, d.email = $email
            WITH d
            MATCH (r:Repository {id: $repoId})
            MERGE (d)-[:WORKS_ON]->(r)
            """,
            id=developer.id,
            repoId=repo_id,
            name=developer.name,
            email=developer.email,
        )
    tx.run(
        """
        MATCH (:Developer {repoId: $repoId})-[r:AUTHORED]->(:File {repoId: $repoId})
        DELETE r
        """,
        repoId=repo_id,
    )
    for batch in _chunks([{"dev": dev, "file": file_id, "commits": count} for dev, file_id, count in doc.authored]):
        tx.run(
            """
            UNWIND $rows AS row
            MATCH (d:Developer {id: row.dev})
            MATCH (f:File {id: row.file})
            MERGE (d)-[r:AUTHORED]->(f)
            SET r.commits = row.commits
            """,
            rows=batch,
        )
    _replace_sourced(
        tx,
        repo_id,
        "Decision",
        "adr",
        [item.id for item in doc.decisions if item.source == "adr"],
    )
    if doc.memory_loaded:
        _replace_sourced(
            tx,
            repo_id,
            "Decision",
            "memory",
            [item.id for item in doc.decisions if item.source == "memory"],
        )
    for decision in doc.decisions:
        tx.run(
            """
            MERGE (d:Decision {id: $id})
            SET d.repoId = $repoId, d.slug = $slug, d.title = $title, d.status = $status,
                d.rationale = $rationale, d.context = $context, d.consequences = $consequences,
                d.date = $date, d.path = $path, d.source = $source
            WITH d
            OPTIONAL MATCH (d)-[r:ABOUT|DECIDED_BY|SUPERSEDES|CHOOSES]->()
            DELETE r
            """,
            id=decision.id,
            repoId=repo_id,
            slug=decision.slug,
            title=decision.title,
            status=decision.status,
            rationale=decision.rationale,
            context=decision.context,
            consequences=decision.consequences,
            date=decision.date,
            path=decision.path,
            source=decision.source,
        )
        if decision.about_ids:
            tx.run(
                """
                MATCH (d:Decision {id: $id})
                MATCH (n {repoId: $repoId})
                WHERE n.id IN $about
                MERGE (d)-[:ABOUT]->(n)
                """,
                id=decision.id,
                repoId=repo_id,
                about=decision.about_ids,
            )
        if decision.decider_ids:
            tx.run(
                """
                MATCH (d:Decision {id: $id})
                MATCH (dev:Developer)
                WHERE dev.id IN $deciders
                MERGE (d)-[:DECIDED_BY]->(dev)
                """,
                id=decision.id,
                deciders=decision.decider_ids,
            )
        if decision.technology_ids:
            tx.run(
                """
                MATCH (d:Decision {id: $id})
                MATCH (t:Technology)
                WHERE t.id IN $techs
                MERGE (d)-[:CHOOSES]->(t)
                """,
                id=decision.id,
                techs=decision.technology_ids,
            )
        if decision.informed_by_ids:
            tx.run(
                """
                MATCH (d:Decision {id: $id})
                MATCH (s:Solution)
                WHERE s.id IN $solutions
                MERGE (s)-[:INFORMS]->(d)
                """,
                id=decision.id,
                solutions=decision.informed_by_ids,
            )
    by_slug = {item.slug: item.id for item in doc.decisions}
    for decision in doc.decisions:
        if not decision.supersedes_slug:
            continue
        target = by_slug.get(decision.supersedes_slug)
        if not target:
            continue
        tx.run(
            """
            MATCH (d:Decision {id: $id})
            MATCH (old:Decision {id: $old})
            MERGE (d)-[:SUPERSEDES]->(old)
            """,
            id=decision.id,
            old=target,
        )

    if doc.memory_loaded:
        for label, source, ids in (
            ("Issue", "memory", [item.id for item in doc.issues if item.source == "memory"]),
            ("Error", "memory", [item.id for item in doc.errors if item.source == "memory"]),
            ("Solution", "memory", [item.id for item in doc.solutions if item.source == "memory"]),
            ("PullRequest", "memory", [item.id for item in doc.pull_requests if item.source == "memory"]),
        ):
            _replace_sourced(tx, repo_id, label, source, ids)
    _replace_sourced(tx, repo_id, "Issue", "github", [item.id for item in doc.issues if item.source == "github"])
    _replace_sourced(tx, repo_id, "Error", "github", [item.id for item in doc.errors if item.source == "github"])
    _replace_sourced(
        tx,
        repo_id,
        "PullRequest",
        "github",
        [item.id for item in doc.pull_requests if item.source == "github"],
    )

    for issue in doc.issues:
        tx.run(
            """
            MERGE (i:Issue {id: $id})
            SET i.repoId = $repoId, i.key = $key, i.title = $title, i.status = $status,
                i.description = $description, i.source = $source, i.url = $url,
                i.labelsJson = $labelsJson, i.assigneesJson = $assigneesJson,
                i.comments = $comments, i.closedAt = $closedAt
            WITH i
            OPTIONAL MATCH (i)-[r:AFFECTS]->()
            DELETE r
            """,
            id=issue.id,
            repoId=repo_id,
            key=issue.key,
            title=issue.title,
            status=issue.status,
            description=issue.description,
            source=issue.source,
            url=issue.url,
            labelsJson=json.dumps(issue.labels),
            assigneesJson=json.dumps(issue.assignees),
            comments=issue.comments,
            closedAt=issue.closed_at,
        )
        _link_about(tx, "Issue", issue.id, repo_id, issue.about_ids, "AFFECTS")
        tx.run(
            """
            MATCH (r:Repository {id: $repoId})
            MATCH (i:Issue {id: $id})
            MERGE (r)-[:HAS_ISSUE]->(i)
            MERGE (i)-[:AFFECTS]->(r)
            """,
            repoId=repo_id,
            id=issue.id,
        )
    for error in doc.errors:
        tx.run(
            """
            MERGE (e:Error {id: $id})
            SET e.repoId = $repoId, e.key = $key, e.type = $type, e.message = $message, e.source = $source
            WITH e
            OPTIONAL MATCH (e)-[r:OCCURS_IN]->()
            DELETE r
            """,
            id=error.id,
            repoId=repo_id,
            key=error.key,
            type=error.type,
            message=error.message,
            source=error.source,
        )
        _link_about(tx, "Error", error.id, repo_id, error.about_ids, "OCCURS_IN")
    for issue in doc.issues:
        if issue.caused_error_ids:
            tx.run(
                """
                MATCH (i:Issue {id: $id})
                MATCH (e:Error)
                WHERE e.id IN $errors
                MERGE (i)-[:CAUSED]->(e)
                """,
                id=issue.id,
                errors=issue.caused_error_ids,
            )
    for solution in doc.solutions:
        tx.run(
            """
            MERGE (s:Solution {id: $id})
            SET s.repoId = $repoId, s.key = $key, s.summary = $summary, s.source = $source
            WITH s
            OPTIONAL MATCH (s)-[r:RESOLVES]->()
            DELETE r
            """,
            id=solution.id,
            repoId=repo_id,
            key=solution.key,
            summary=solution.summary,
            source=solution.source,
        )
        targets = solution.resolves_issue_ids + solution.resolves_error_ids
        if targets:
            tx.run(
                """
                MATCH (s:Solution {id: $id})
                MATCH (n)
                WHERE n.id IN $targets
                MERGE (s)-[:RESOLVES]->(n)
                """,
                id=solution.id,
                targets=targets,
            )
        if solution.resolves_issue_ids:
            tx.run(
                """
                MATCH (s:Solution {id: $id})
                MATCH (d:Decision {repoId: $repoId})-[:ABOUT]->(n)
                MATCH (i:Issue)-[:AFFECTS]->(n)
                WHERE i.id IN $issues
                MERGE (s)-[:INFORMS]->(d)
                """,
                id=solution.id,
                repoId=repo_id,
                issues=solution.resolves_issue_ids,
            )
    for pull in doc.pull_requests:
        tx.run(
            """
            MERGE (pr:PullRequest {id: $id})
            SET pr.repoId = $repoId, pr.number = $number, pr.title = $title, pr.status = $status,
                pr.url = $url, pr.source = $source, pr.body = $body, pr.merged = $merged,
                pr.draft = $draft, pr.base = $base, pr.head = $head, pr.mergedAt = $mergedAt,
                pr.labelsJson = $labelsJson
            WITH pr
            OPTIONAL MATCH (pr)-[r:CHANGES|AUTHORED_BY|CLOSES]->()
            DELETE r
            """,
            id=pull.id,
            repoId=repo_id,
            number=pull.number,
            title=pull.title,
            status=pull.status,
            url=pull.url,
            source=pull.source,
            body=pull.body,
            merged=pull.merged,
            draft=pull.draft,
            base=pull.base,
            head=pull.head,
            mergedAt=pull.merged_at,
            labelsJson=json.dumps(pull.labels),
        )
        if pull.file_ids:
            tx.run(
                """
                MATCH (pr:PullRequest {id: $id})
                MATCH (f:File)
                WHERE f.id IN $files
                MERGE (pr)-[:CHANGES]->(f)
                """,
                id=pull.id,
                files=pull.file_ids,
            )
        if pull.author_id:
            tx.run(
                """
                MATCH (pr:PullRequest {id: $id})
                MATCH (dev:Developer {id: $dev})
                MERGE (pr)-[:AUTHORED_BY]->(dev)
                """,
                id=pull.id,
                dev=pull.author_id,
            )
        tx.run(
            """
            MATCH (r:Repository {id: $repoId})
            MATCH (pr:PullRequest {id: $id})
            MERGE (r)-[:HAS_PR]->(pr)
            """,
            repoId=repo_id,
            id=pull.id,
        )
        if pull.closes_issue_ids:
            tx.run(
                """
                MATCH (pr:PullRequest {id: $id})
                MATCH (i:Issue)
                WHERE i.id IN $issues
                MERGE (pr)-[:CLOSES]->(i)
                """,
                id=pull.id,
                issues=pull.closes_issue_ids,
            )


def _replace_sourced(tx, repo_id: str, label: str, source: str, keep: list[str]) -> None:
    tx.run(
        f"""
        MATCH (n:{label} {{repoId: $repoId, source: $source}})
        WHERE NOT n.id IN $keep
        DETACH DELETE n
        """,
        repoId=repo_id,
        source=source,
        keep=keep,
    )


def _link_about(tx, label: str, node_id_value: str, repo_id: str, about_ids: list[str], rel: str) -> None:
    if not about_ids:
        return
    tx.run(
        f"""
        MATCH (a:{label} {{id: $id}})
        MATCH (n {{repoId: $repoId}})
        WHERE n.id IN $about
        MERGE (a)-[:{rel}]->(n)
        """,
        id=node_id_value,
        repoId=repo_id,
        about=about_ids,
    )


def _file_row(item) -> dict:
    return {
        "id": item.id,
        "path": item.path,
        "name": item.name,
        "language": item.language,
        "loc": item.loc,
        "sha256": item.sha256,
        "directoryId": item.directory_id,
        "docstring": item.docstring,
        "imports": item.imports,
    }


def _symbol_row(item) -> dict:
    return {
        "id": item.id,
        "name": item.name,
        "qualifiedName": item.qualified_name,
        "fileId": item.file_id,
        "filePath": item.file_path,
        "line": item.line,
        "docstring": item.docstring,
        "signature": item.signature,
        "kind": item.kind,
        "className": item.class_name,
        "bases": item.bases,
        "classId": None,
    }


def _dir_row(item) -> dict:
    return {"id": item.id, "path": item.path, "name": item.name, "parentId": item.parent_id}


def _sort_tree(node: dict) -> None:
    children = node.get("children") or []
    children.sort(key=lambda item: (item.get("type") != "dir", (item.get("name") or "").lower()))
    for child in children:
        _sort_tree(child)


def _accumulate(found: dict[str, dict], row, boost: float) -> None:
    labels = list(row["labels"])
    label = labels[0] if labels else "Node"
    weights = {
        "Decision": 8,
        "Function": 6,
        "Class": 6,
        "Issue": 5,
        "Solution": 5,
        "Error": 4,
        "File": 4,
        "Technology": 4,
        "PullRequest": 3,
        "Developer": 2,
        "Conversation": 1,
        "Directory": 1,
        "Repository": 0,
    }
    score = weights.get(label, 1) + boost
    current = found.get(row["id"])
    if current is None or score > current["score"]:
        found[row["id"]] = {
            "id": row["id"],
            "label": label,
            "name": row["name"],
            "score": score,
        }


def _chunks(items: list, size: int = 400):
    for index in range(0, len(items), size):
        yield items[index : index + size]


def _expand_ids(session, repo_id: str, seed_ids: list[str]) -> list[str]:
    ids = [item for item in seed_ids if item]
    if not ids:
        return []
    expanded: set[str] = set(ids)
    row = session.run(
        """
        MATCH (n {repoId: $repoId})
        WHERE n.id IN $ids
        OPTIONAL MATCH (file:File)-[:DEFINES]->(n)
        OPTIONAL MATCH (n)-[:DEFINES]->(fn:Function)
        OPTIONAL MATCH (n)-[:DEFINES]->(cls:Class)
        RETURN collect(DISTINCT file.id) AS files,
               collect(DISTINCT fn.id)[..25] AS functions,
               collect(DISTINCT cls.id)[..25] AS classes
        """,
        repoId=repo_id,
        ids=ids,
    ).single()
    if row:
        for key in ("files", "functions", "classes"):
            expanded.update(item for item in (row[key] or []) if item)
    current = list(expanded)
    queries = [
        """
        MATCH (d:Decision {repoId: $repoId})-[:ABOUT]->(n)
        WHERE d.id IN $ids AND NOT n:Repository
        RETURN collect(DISTINCT n.id)[..20] AS ids
        """,
        """
        MATCH (d:Decision {repoId: $repoId})-[:ABOUT]->(n)
        WHERE n.id IN $ids
        RETURN collect(DISTINCT d.id)[..8] AS ids
        """,
        """
        MATCH (i:Issue {repoId: $repoId})-[:AFFECTS]->(n)
        WHERE i.id IN $ids AND NOT n:Repository
        RETURN collect(DISTINCT n.id)[..15] AS ids
        """,
        """
        MATCH (f:File {repoId: $repoId})-[:USES]->(t:Technology)
        WHERE t.id IN $ids
        RETURN collect(DISTINCT f.id)[..15] AS ids
        """,
    ]
    for query in queries:
        linked = session.run(query, repoId=repo_id, ids=current).single()
        if linked:
            expanded.update(item for item in (linked["ids"] or []) if item)
    return list(expanded)[:60]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(title: str) -> str:
    cleaned = "".join(char.lower() if char.isalnum() else "-" for char in title)
    return "-".join(part for part in cleaned.split("-") if part)[:80]


def _load_json(value, fallback):
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback
