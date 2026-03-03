from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import yaml


def load_yaml(path: str | Path) -> Dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"YAML not found: {p}")
    with p.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def ensure_dir(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


def write_text(path: Path, text: str) -> None:
    ensure_dir(path.parent)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, obj: Any) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True), encoding="utf-8")


def repo_root_from_this_file() -> Path:
    # extraction/scripts/common.py -> extraction/scripts -> extraction -> repo root
    return Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class RunPaths:
    repo_root: Path
    compiled_dir: Path
    outputs_dir: Path

    @staticmethod
    def from_config(cfg: Dict[str, Any]) -> "RunPaths":
        root = repo_root_from_this_file()
        run_id = cfg["run"]["run_id"]

        compiled_base = cfg["run"].get("compiled_sql_dir", "extraction/compiled_sql")
        outputs_base = cfg["run"].get("output_dir", "extraction/outputs")

        compiled_dir = root / compiled_base / run_id
        outputs_dir = root / outputs_base / run_id
        return RunPaths(repo_root=root, compiled_dir=compiled_dir, outputs_dir=outputs_dir)


def deep_merge(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    """Return merged dict: values from b override/extend a."""
    out = dict(a)
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def validate_min_config(cfg: Dict[str, Any]) -> None:
    for key in ["run", "globals", "outputs"]:
        if key not in cfg:
            raise ValueError(f"Config missing required top-level key: '{key}'")
    if "run_id" not in cfg["run"]:
        raise ValueError("Config missing required key: run.run_id")
    if not isinstance(cfg["outputs"], dict) or not cfg["outputs"]:
        raise ValueError("Config outputs must be a non-empty mapping")
    # enforce uniqueness of output_file names
    seen = set()
    for name, spec in cfg["outputs"].items():
        if "sql_file" not in spec:
            raise ValueError(f"Output '{name}' missing sql_file")
        if "output_file" not in spec:
            raise ValueError(f"Output '{name}' missing output_file")
        of = spec["output_file"]
        if of in seen:
            raise ValueError(f"Duplicate output_file '{of}' in outputs")
        seen.add(of)