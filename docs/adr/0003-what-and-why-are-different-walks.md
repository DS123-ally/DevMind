# What and why are different walks

Status: accepted
Date: 2026-09-26
Deciders: DevMind

## Context
"What does this function do?" and "Why does it work this way?" are not two tones of the same answer. One walks definitions and calls. The other walks decisions, issues, errors, solutions, and pull requests.

## Decision
DevMind classifies the question, retrieves the matching subgraph, and keeps the two kinds of facts in separate parts of the briefing.

## Consequences
A what-question can still surface a linked decision. A why-question with no recorded decision reports the gap instead of guessing.

Affects: backend/app/reasoning/query.py, backend/app/reasoning/engine.py
