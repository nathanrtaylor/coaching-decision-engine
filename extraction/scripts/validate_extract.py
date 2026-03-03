from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

from common import RunPaths, load_yaml, validate_min_config


def validate_outputs(cfg_path: Path) -> None:
    cfg = load_yaml(cfg_path)
    validate_min_config(cfg)
    paths = RunPaths.from_config(cfg)

    failures: List[str] = []

    for out_name, spec in cfg["outputs"].items():
        p = paths.outputs_dir / spec["output_file"]
        if not p.exists():
            failures.append(f"Missing output file: {p}")
            continue

        # optional: require non-empty if flagged
        require_rows = bool(spec.get("require_rows", False))
        if require_rows:
            df = pd.read_csv(p)
            if df.empty:
                failures.append(f"Output '{out_name}' is empty but require_rows=true: {p}")

        # optional: column expectations
        expected = spec.get("expected_columns")
        if expected:
            df = pd.read_csv(p, nrows=5)
            missing = [c for c in expected if c not in df.columns]
            if missing:
                failures.append(f"Output '{out_name}' missing columns {missing}: {p}")

    if failures:
        msg = "Extraction validation failed:\n" + "\n".join(f"- {x}" for x in failures)
        raise SystemExit(msg)

    print(f"Extraction validation passed for run_id={cfg['run']['run_id']}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    args = ap.parse_args()
    validate_outputs(Path(args.config))


if __name__ == "__main__":
    main()