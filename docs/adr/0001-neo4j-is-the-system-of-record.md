# Neo4j is the system of record

Status: accepted
Date: 2026-09-26
Deciders: DevMind

## Context
A transcript can recall that a question was asked. It cannot recall that a decision constrains a function, or that a pull request changed the file where an error occurred.

## Decision
Repository, directory, file, class, function, technology, issue, error, solution, pull request, technical decision, developer, and conversation are nodes in Neo4j. Answers are walks over those relationships.

## Consequences
DevMind does not answer from a chat log. If the graph does not contain a rationale, the briefing says so.

Affects: backend/app/graph/store.py, backend/app/reasoning/engine.py
