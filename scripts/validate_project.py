from pathlib import Path
from collections import Counter
import ast
import json
import yaml

root = Path(__file__).resolve().parents[1]
for py in (root / "crawler" / "crawler").rglob("*.py"):
    ast.parse(py.read_text(encoding="utf-8"), filename=str(py))

cfg = yaml.safe_load((root / "config" / "sources.yaml").read_text(encoding="utf-8"))
sources = cfg["sources"]
assert 30 <= len(sources) <= 50, len(sources)
assert sum(1 for v in sources.values() if v.get("region") == "VN") >= 10
assert all(v.get("discovery") in {"rss", "html", "sitemap"} for v in sources.values())
assert all((v.get("feed_url") if v.get("discovery") == "rss" else v.get("start_url") or v.get("sitemap_url")) for v in sources.values())

sample = root / "output" / "sample_articles.jsonl"
if sample.exists():
    for line in sample.read_text(encoding="utf-8").splitlines():
        if line.strip():
            obj = json.loads(line)
            assert obj["url"].startswith("http")
            assert obj["title"]

print("OK: Python syntax and YAML configuration are valid")
print("Sources:", len(sources))
print("Regions:", dict(Counter(v.get("region") for v in sources.values())))
print("Discovery:", dict(Counter(v.get("discovery") for v in sources.values())))
