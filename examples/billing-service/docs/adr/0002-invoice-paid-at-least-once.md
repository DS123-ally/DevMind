# Treat invoice.paid as at-least-once

Status: accepted
Date: 2024-06-03
Deciders: Lena Ortiz

## Context
Stripe retries webhooks. The first version of apply_payment inserted a payment row on every invoice.paid delivery and raised IntegrityError when the retry arrived.

## Decision
apply_payment records a stable payment key and returns the existing key when Stripe delivers invoice.paid again.

## Consequences
Handlers must not assume a webhook call is the first successful call.

Affects: app/webhooks.py, apply_payment
