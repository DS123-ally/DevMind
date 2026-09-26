"""Stripe webhook entry points.

invoice.paid is at-least-once, so apply_payment must be safe to retry.
"""

from app.store import InvoiceStore


def handle_stripe_event(event: dict, store: InvoiceStore) -> str | None:
    """Apply invoice.paid and ignore every other Stripe event."""
    if event.get("type") != "invoice.paid":
        return None
    invoice_id = event["data"]["object"]["id"]
    return apply_payment(store, invoice_id)


def apply_payment(store: InvoiceStore, invoice_id: str) -> str:
    """Record a payment once, even when Stripe retries the webhook."""
    return store.record_payment(invoice_id)
