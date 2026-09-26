# Use floating-point dollars

Status: superseded
Date: 2023-11-02
Deciders: Lena Ortiz

## Context
Early invoices stored totals as binary floats because that matched the JSON examples in the first prototype.

## Decision
Store invoice amounts as floating-point dollar values and compute tax with float multiplication.

## Consequences
Totals drifted by fractions of a cent, and payment reconciliation did not match the bank.

Affects: app/pricing.py, calculate_tax
