from pathlib import Path
import ast
import json

root = Path(__file__).resolve().parents[1]

for py in (root / "crawler" / "crawler").rglob("*.py"):
    ast.parse(py.read_text(encoding="utf-8"), filename=str(py))

try:
    import yaml
    cfg = yaml.safe_load((root / "config" / "sources.yaml").read_text(encoding="utf-8"))
    assert len(cfg["sources"]) >= 3
except ImportError:
    # Basic validation if yaml is not installed on host
    content = (root / "config" / "sources.yaml").read_text(encoding="utf-8")
    assert "cafef_stock:" in content
    assert "vnexpress_business:" in content
    assert "investing_stock_market:" in content

for line in (root / "output" / "sample_articles.jsonl").read_text(encoding="utf-8").splitlines():
    obj = json.loads(line)
    assert obj["url"].startswith("http")
    assert obj["title"]

print("OK: Python syntax, YAML config and sample JSONL are valid")
