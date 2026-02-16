from __future__ import annotations

import argparse
from pathlib import Path

from cde.governance.audit import RunAuditor
from cde.governance.versioning import resolve_active_config
from cde.utils.io import read_parquet_or_csv, ensure_dir
from cde.engine.recommend import recommend_for_population
from cde.engine.receipts import build_receipts
from cde.simulation.exports import export_run_artifacts


def main() -> None:
    parser = argparse.ArgumentParser(description="Run engine given pre-built candidate table.")
    parser.add_argument("--candidates", type=str, required=True, help="Path to candidates file (csv/parquet)")
    parser.add_argument("--signals", type=str, required=False, help="Optional path to signals file (csv/parquet)")
    parser.add_argument("--scores", type=str, required=False, help="Optional path to scores file (csv/parquet)")
    parser.add_argument("--out-dir", type=str, required=True, help="Path to outputs/runs/<timestamp>")
    parser.add_argument("--configs-dir", type=str, default="configs")
    args = parser.parse_args()

    candidates_path = Path(args.candidates)
    out_dir = Path(args.out_dir)
    configs_dir = Path(args.configs_dir)
    ensure_dir(out_dir)

    config = resolve_active_config(configs_dir)

    auditor = RunAuditor(out_dir=out_dir)
    auditor.start_run()
    auditor.record_inputs(raw_dir=None, config=config, extra_inputs={"candidates": str(candidates_path)})

    candidates = read_parquet_or_csv(candidates_path)

    recs = recommend_for_population(candidates, config)

    signals = read_parquet_or_csv(Path(args.signals)) if args.signals else None
    scores = read_parquet_or_csv(Path(args.scores)) if args.scores else None

    receipts = build_receipts(recs, candidates, signals, scores, config, excluded_signals=None)

    export_run_artifacts(out_dir, auditor, recs, receipts, config, excluded_signals=None)
    auditor.finish_run()

    print(f"Done. Wrote outputs to: {out_dir}")


if __name__ == "__main__":
    main()
