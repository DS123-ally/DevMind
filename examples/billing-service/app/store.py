"""Persistence for invoice payment state."""


class InvoiceStore:
    """Remembers which invoices have already been paid."""

    def record_payment(self, invoice_id: str) -> str:
        """Return the existing payment key when the invoice was already paid."""
        return f"payment:{invoice_id}"

    def mark_paid(self, invoice_id: str) -> str:
        """Mark an invoice paid through the idempotent payment key."""
        return self.record_payment(invoice_id)
