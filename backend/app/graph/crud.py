"""CRUD for DevMind graph nodes. All writes are MERGE + SET; deletes DETACH DELETE."""

from __future__ import annotations

from typing import Any

from neo4j import Driver

LABELS = frozenset({
    "Repository", "Directory", "File", "Class", "Function", "Technology",
    "Issue", "Error", "Solution", "PullRequest", "Decision", "Developer",
    "Conversation", "Message",
})
RELS = frozenset({
    "CONTAINS", "DEFINES", "IMPORTS", "CALLS", "EXTENDS", "USES", "ABOUT",
    "DECIDED_BY", "WORKS_ON", "AUTHORED", "CHOOSES", "INFORMS", "SUPERSEDES",
    "HAS_ISSUE", "AFFECTS", "CAUSED", "RESOLVES", "HAS_PR", "CHANGES",
    "AUTHORED_BY", "CLOSES", "HAS_MESSAGE", "IN_REPOSITORY",
})


class GraphCrud:
    def __init__(self, driver: Driver, database: str) -> None:
        self.driver = driver
        self.database = database

    def create_or_update(self, label: str, node_id: str, props: dict[str, Any], repo_id: str | None = None) -> dict:
        if label not in LABELS:
            raise ValueError(f"Unknown label {label}")
        extra = dict(props)
        if repo_id:
            extra["repoId"] = repo_id
        extra["id"] = node_id
        query = f"""
        MERGE (n:{label} {{id: $id}})
        SET n += $props
        RETURN n.id AS id, labels(n) AS labels, properties(n) AS props
        """
        with self.driver.session(database=self.database) as session:
            record = session.run(query, id=node_id, props=extra).single()
        if record is None:
            raise LookupError("Could not write node")
        return dict(record)

    def read(self, node_id: str, repo_id: str | None = None) -> dict | None:
        query = """
        MATCH (n {id: $id})
        WHERE $repoId IS NULL OR n.repoId = $repoId OR n.id = $repoId
        OPTIONAL MATCH (n)-[r]->(m)
        RETURN n.id AS id, labels(n) AS labels, properties(n) AS props,
               collect(DISTINCT {type: type(r), target: m.id, targetLabels: labels(m)}) AS outgoing
        """
        with self.driver.session(database=self.database) as session:
            record = session.run(query, id=node_id, repoId=repo_id).single()
        return dict(record) if record else None

    def update(self, node_id: str, props: dict[str, Any], repo_id: str | None = None) -> dict:
        query = """
        MATCH (n {id: $id})
        WHERE $repoId IS NULL OR n.repoId = $repoId
        SET n += $props
        RETURN n.id AS id, labels(n) AS labels, properties(n) AS props
        """
        with self.driver.session(database=self.database) as session:
            record = session.run(query, id=node_id, repoId=repo_id, props=props).single()
        if record is None:
            raise LookupError("Node not found")
        return dict(record)

    def delete(self, node_id: str, repo_id: str | None = None) -> bool:
        query = """
        MATCH (n {id: $id})
        WHERE $repoId IS NULL OR n.repoId = $repoId
        WITH n LIMIT 1
        DETACH DELETE n
        RETURN count(*) AS removed
        """
        with self.driver.session(database=self.database) as session:
            record = session.run(query, id=node_id, repoId=repo_id).single()
        return bool(record and record["removed"])

    def link(self, source_id: str, rel: str, target_id: str, repo_id: str | None = None) -> None:
        if rel not in RELS:
            raise ValueError(f"Unknown relationship {rel}")
        query = f"""
        MATCH (a {{id: $source}}), (b {{id: $target}})
        WHERE ($repoId IS NULL OR a.repoId = $repoId) AND ($repoId IS NULL OR b.repoId = $repoId)
        MERGE (a)-[:{rel}]->(b)
        """
        with self.driver.session(database=self.database) as session:
            session.run(query, source=source_id, target=target_id, repoId=repo_id).consume()

    def seed(self, statements: list[str], repo_id: str) -> dict:
        last: dict = {}
        with self.driver.session(database=self.database) as session:
            for statement in statements:
                result = session.run(statement, repoId=repo_id)
                row = result.single()
                if row:
                    last = dict(row)
        return last
