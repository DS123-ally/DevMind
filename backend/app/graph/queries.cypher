// Named Cypher for Neo4j Browser and GraphStore.
// Set :param repoId => '…' before running repo-scoped queries.

// name: list_projects
MATCH (r:Repository)
OPTIONAL MATCH (f:File {repoId: r.id})
RETURN r.id AS id, r.name AS name, r.path AS path, r.summary AS summary,
       r.updatedAt AS updatedAt, r.githubUrl AS githubUrl, count(f) AS files
ORDER BY r.updatedAt DESC;

// name: get_node
MATCH (n {id: $nodeId})
WHERE $repoId IS NULL OR n.repoId = $repoId OR n.id = $repoId
RETURN labels(n) AS labels, properties(n) AS props;

// name: inventory
MATCH (n {repoId: $repoId})
RETURN labels(n)[0] AS label, count(n) AS count
ORDER BY label;

// name: relationships
MATCH (a {repoId: $repoId})-[r]->()
RETURN type(r) AS type, count(r) AS count
ORDER BY count DESC;

// name: why_path
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
LIMIT 8;

// name: calls_for_symbol
MATCH (fn:Function {repoId: $repoId, name: $name})
OPTIONAL MATCH (fn)-[:CALLS]->(callees)
OPTIONAL MATCH (callers)-[:CALLS]->(fn)
RETURN fn.name AS name, fn.qualifiedName AS qualifiedName, fn.line AS line,
       collect(DISTINCT callees.name) AS calls,
       collect(DISTINCT callers.name) AS calledBy;

// name: file_defines
MATCH (f:File {repoId: $repoId, path: $path})-[:DEFINES]->(s)
RETURN labels(s)[0] AS kind, s.name AS name, s.line AS line, s.signature AS signature
ORDER BY s.line;

// name: search
CALL db.index.fulltext.queryNodes('devmind_search', $q) YIELD node, score
WHERE node.repoId = $repoId
RETURN node.id AS id, labels(node) AS labels,
       coalesce(node.name, node.title, node.key, node.path, '') AS name, score
LIMIT 20;

// name: decisions
MATCH (d:Decision {repoId: $repoId})
OPTIONAL MATCH (d)-[:CHOOSES]->(t:Technology)
OPTIONAL MATCH (s:Solution)-[:INFORMS]->(d)
WITH d, collect(DISTINCT t.name) AS technologies, collect(DISTINCT s.summary) AS solutions
ORDER BY d.date DESC
RETURN d.id AS id, d.title AS title, d.status AS status, d.rationale AS rationale,
       d.source AS source, technologies, solutions;

// name: issues
MATCH (i:Issue {repoId: $repoId})
OPTIONAL MATCH (i)-[:CAUSED]->(e:Error)
OPTIONAL MATCH (sol:Solution)-[:RESOLVES]->(i)
OPTIONAL MATCH (pr:PullRequest)-[:CLOSES]->(i)
RETURN i.id AS id, i.key AS key, i.title AS title, i.status AS status,
       collect(DISTINCT e.type) AS errors, collect(DISTINCT sol.summary) AS solutions,
       collect(DISTINCT pr.number) AS pulls;

// name: subgraph
MATCH (n {repoId: $repoId})
WHERE n:Technology OR n:Decision OR n:Issue OR n:Solution OR n:PullRequest OR n:Error
   OR n.id IN $seeds
WITH n LIMIT 90
OPTIONAL MATCH (n)-[r]->(m {repoId: $repoId})
RETURN collect(DISTINCT {id: n.id, labels: labels(n), name: coalesce(n.name, n.title, n.key, n.path, '')}) AS nodes,
       collect(DISTINCT CASE WHEN m IS NULL THEN null ELSE {source: n.id, target: m.id, type: type(r)} END) AS edges;
