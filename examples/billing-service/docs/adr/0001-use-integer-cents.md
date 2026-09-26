# Store money as integer cents

Status: accepted
Date: 2024-02-12
Deciders: Lena Ortiz
Supersedes: 0000-use-floating-point-dollars

## Context
Invoice totals drifted by fractions of a cent when tax was computed with binary floating point.

## Decision
All monetary amounts are integer cents. Tax rates are basis points. calculate_tax uses integer division.

## Consequences
Callers must not pass float dollar amounts. Display formatting happens at the edge.

Affects: app/pricing.py, calculate_tax, preview_invoice
