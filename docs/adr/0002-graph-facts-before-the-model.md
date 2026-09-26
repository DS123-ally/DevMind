# Briefings are composed from graph facts first

Status: accepted
Date: 2026-09-26
Deciders: DevMind

## Context
A language model asked to explain a repository will invent a plausible reason when the repository never recorded one.

## Decision
The briefing bullets are produced from the subgraph that was retrieved. A model may rephrase those bullets only when each sentence still overlaps the retrieved facts. Evidence relationships are never taken from the model.

## Consequences
Turning the model off still produces a briefing. Turning it on cannot add a rationale the graph does not have.

Affects: backend/app/reasoning/narrator.py, backend/app/reasoning/llm.py
