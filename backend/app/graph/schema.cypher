// DevMind Neo4j schema — constraints, indexes, full-text search.
// Applied at API startup via GraphStore.ensure_schema().

CREATE CONSTRAINT repository_id IF NOT EXISTS FOR (n:Repository) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT directory_id IF NOT EXISTS FOR (n:Directory) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT file_id IF NOT EXISTS FOR (n:File) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT class_id IF NOT EXISTS FOR (n:Class) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT function_id IF NOT EXISTS FOR (n:Function) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT technology_id IF NOT EXISTS FOR (n:Technology) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT issue_id IF NOT EXISTS FOR (n:Issue) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT error_id IF NOT EXISTS FOR (n:Error) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT solution_id IF NOT EXISTS FOR (n:Solution) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT pullrequest_id IF NOT EXISTS FOR (n:PullRequest) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT decision_id IF NOT EXISTS FOR (n:Decision) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT developer_id IF NOT EXISTS FOR (n:Developer) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT conversation_id IF NOT EXISTS FOR (n:Conversation) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT message_id IF NOT EXISTS FOR (n:Message) REQUIRE n.id IS UNIQUE;

CREATE INDEX file_repo IF NOT EXISTS FOR (n:File) ON (n.repoId);
CREATE INDEX function_repo IF NOT EXISTS FOR (n:Function) ON (n.repoId);
CREATE INDEX function_repo_name IF NOT EXISTS FOR (n:Function) ON (n.repoId, n.name);
CREATE INDEX class_repo IF NOT EXISTS FOR (n:Class) ON (n.repoId);
CREATE INDEX decision_repo IF NOT EXISTS FOR (n:Decision) ON (n.repoId);
CREATE INDEX issue_repo IF NOT EXISTS FOR (n:Issue) ON (n.repoId);
CREATE INDEX technology_repo IF NOT EXISTS FOR (n:Technology) ON (n.repoId);
CREATE INDEX conversation_repo IF NOT EXISTS FOR (n:Conversation) ON (n.repoId);

CREATE FULLTEXT INDEX devmind_search IF NOT EXISTS
FOR (n:File|Directory|Class|Function|Technology|Issue|Error|Solution|PullRequest|Decision|Developer|Conversation|Repository)
ON EACH [n.name, n.title, n.qualifiedName, n.path, n.summary, n.rationale, n.context, n.message, n.description, n.signature, n.headline, n.question, n.key];
