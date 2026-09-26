from app.ingest.gitlog import parse_git_log
from app.ingest.parsers import parse_adr, parse_javascript, parse_python


def test_python_parser_reads_methods_and_calls():
    source = '''
class InvoiceStore:
    """Store invoices."""

    def record_payment(self, invoice_id: str) -> str:
        """Record one payment."""
        return invoice_id

def apply_payment(store):
    """Apply a payment."""
    return store.record_payment("in_1")
'''
    parsed = parse_python(source)
    assert parsed.classes[0].name == "InvoiceStore"
    names = {item.name: item for item in parsed.functions}
    assert names["record_payment"].class_name == "InvoiceStore"
    assert "record_payment" in names["apply_payment"].calls


def test_javascript_parser_reads_class_methods():
    source = """
export class Tax {
  total(cents) {
    return this.calculate(cents);
  }
}
export function calculate(cents) {
  return cents;
}
"""
    parsed = parse_javascript(source)
    assert parsed.classes[0].name == "Tax"
    names = {item.name for item in parsed.functions}
    assert "total" in names
    assert "calculate" in names


def test_adr_parser_keeps_supersession_direction():
    text = """
# Store money as integer cents

Status: accepted
Date: 2024-02-12
Deciders: Lena Ortiz
Supersedes: 0000-use-floating-point-dollars

## Context
Floats drifted.

## Decision
Use integer cents.

## Consequences
Format at the edge.

Affects: app/pricing.py, calculate_tax
"""
    parsed = parse_adr("docs/adr/0001-use-integer-cents.md", text)
    assert parsed is not None
    assert parsed.supersedes == "0000-use-floating-point-dollars"
    assert parsed.affects == ["app/pricing.py", "calculate_tax"]
    assert "integer cents" in parsed.decision


def test_git_log_groups_authors_by_file():
    text = """---Lena Ortiz|lena@example.com
app/pricing.py
app/api.py

---Lena Ortiz|lena@example.com
app/pricing.py
"""
    authorship = parse_git_log(text)
    assert authorship["app/pricing.py"]["lena@example.com"]["count"] == 2
    assert authorship["app/api.py"]["lena@example.com"]["count"] == 1
