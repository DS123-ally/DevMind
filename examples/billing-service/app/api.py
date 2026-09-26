"""Invoice preview at the HTTP edge."""

from app.pricing import calculate_tax, subtotal


def preview_invoice(lines: list[dict], rate_bps: int) -> dict:
    """Return subtotal, tax, and total, all in integer cents."""
    base = subtotal(lines)
    tax = calculate_tax(base, rate_bps)
    return {"subtotal_cents": base, "tax_cents": tax, "total_cents": base + tax}
