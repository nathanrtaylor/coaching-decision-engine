from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import pandas as pd

try:
    import yaml
except Exception:  # pragma: no cover
    yaml = None


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def read_parquet_or_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(str(path))
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    raise ValueError(f"Unsupported file type: {path.suffix}")


def load_yaml(path: Path) -> Dict[str, Any]:
    if yaml is None:
        raise ImportError("pyyaml is required to load yaml configs.")
    if not path.exists():
        raise FileNotFoundError(str(path))
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def dump_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
