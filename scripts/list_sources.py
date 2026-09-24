from pathlib import Path
from collections import Counter
import yaml

root = Path(__file__).resolve().parents[1]
sources = yaml.safe_load((root / "config" / "sources.yaml").read_text(encoding="utf-8"))["sources"]
print(f"Total sources: {len(sources)}")
print("By region:", dict(Counter(v.get("region") for v in sources.values())))
print("By discovery:", dict(Counter(v.get("discovery") for v in sources.values())))
print()
for sid, cfg in sources.items():
    print(f"{sid:32} {cfg.get('region',''):7} {cfg.get('discovery',''):8} {cfg.get('name','')}")
