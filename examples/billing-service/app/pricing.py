"""Invoice money math.

Amounts are integer cents. Tax rates are basis points.
"""


def calculate_tax(subtotal_cents: int, rate_bps: int) -> int:
    """Apply a tax rate expressed in basis points to a cent amount."""
    return (subtotal_cents * rate_bps) // 10_000


def line_amount(line: dict) -> int:
    """Return the cent total for one invoice line."""
    return int(line["unit_cents"]) * int(line["quantity"])


def subtotal(lines: list[dict]) -> int:
    """Sum line amounts into a cent subtotal."""
    total = 0
    for line in lines:
        total += line_amount(line)
    return total
