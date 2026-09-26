from pathlib import Path

from app.ingest.parsers import parse_source
from app.ingest.scanner import SKIP_DIRS, extract_repository
from app.ingest.technologies import technologies_in_manifest
from app.ingest.treesitter import available, parse_with_tree_sitter


def test_scanner_skips_venv(tmp_path: Path):
    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
    nested = tmp_path / ".venv" / "lib"
    nested.mkdir(parents=True)
    (nested / "site.py").write_text("hidden = True\n", encoding="utf-8")
    files = extract_repository(tmp_path)
    assert [item.rel for item in files] == ["app.py"]
    assert ".venv" in SKIP_DIRS


def test_technology_manifests():
    req = technologies_in_manifest("requirements.txt", "fastapi==0.115\nstripe>=7\n")
    names = {name for name, _ in req}
    assert "fastapi" in names
    assert "stripe" in names
    pkgs = technologies_in_manifest("go.mod", "require github.com/gin-gonic/gin v1.9.0\n")
    assert any("gin" in name for name, _ in pkgs)


def test_tree_sitter_python_symbols():
    source = '''
class InvoiceStore:
    def record_payment(self, invoice_id: str) -> str:
        return invoice_id

def apply_payment(store):
    return store.record_payment("in_1")
'''
    parsed = parse_source("app/store.py", source)
    names = {item.name: item for item in parsed.functions}
    assert names["record_payment"].class_name == "InvoiceStore"
    assert "record_payment" in names["apply_payment"].calls
    if available():
        ts = parse_with_tree_sitter("app/store.py", source)
        assert ts is not None
        ts_names = {item.name: item for item in ts.functions}
        assert "record_payment" in ts_names["apply_payment"].calls
