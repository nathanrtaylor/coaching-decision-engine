from __future__ import annotations
from pathlib import Path
import yaml

def load_yaml(path: str | Path) -> dict:
    p = Path(path)
    for enc in ("utf-8", "utf-8-sig"):
        try:
            return yaml.safe_load(p.read_text(encoding=enc))
        except UnicodeDecodeError:
            continue
    # If both fail, surface a clear error
    return yaml.safe_load(p.read_text(encoding="cp1252"))