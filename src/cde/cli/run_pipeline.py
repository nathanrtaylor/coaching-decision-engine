from __future__ import annotations

import argparse
from pathlib import Path

from cde.governance.audit import RunAuditor
from cde.governance.versioning import resolve_active_config
from cde.ingestion.extract import load_raw_exports
from cde.ingestion.normalize import normalize_inputs
from cde.ingestion.validate import validate_inputs
from cde.signals.build_signals import build_signals
from cde.scoring.assemble import assemble_scores
from cde.prioritization.apply import build_topic_candidates
from cde.engine.recommend import recommend_for_population
from cde.engine.receipts import build_receipts
from cde.simulation.exports import export_run_artifacts
from cde.signals.thresholds import apply_signal_thresholds


def main() -> None:
    parser = argparse.ArgumentParser(description="Run end-to-end Coaching Decision Engine pipeline.")
    parser.add_argument("--raw-dir", type=str, required=True, help="Path to a raw export folder (e.g., data/raw/weekly/2026-02-16)")
    parser.add_argument("--out-dir", type=str, required=True, help="Path to outputs/runs/<timestamp> folder to write artifacts")
    parser.add_argument("--configs-dir", type=str, default="configs", help="Path to configs directory")
    parser.add_argument("--run-id", type=str, default=None, help="Optional run id (otherwise derived by auditor)")
    args = parser.parse_args()

    raw_dir = Path(args.raw_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    configs_dir = Path(args.configs_dir)

    config = resolve_active_config(configs_dir)

    auditor = RunAuditor(out_dir=out_dir, run_id=args.run_id)
    auditor.start_run()

    raw = load_raw_exports(raw_dir)
    auditor.record_inputs(raw_dir=raw_dir, config=config)

    normalized = normalize_inputs(raw, config)
    validate_inputs(normalized, config)

    signals = build_signals(normalized, config)
    signals.to_csv(out_dir / "signals.csv", index=False)

    thr_res = apply_signal_thresholds(signals, config)
    eligible_signals = thr_res.eligible_signals
    excluded_signals = thr_res.excluded_signals

    eligible_signals.to_csv(out_dir / "eligible_signals.csv", index=False)
    excluded_signals.to_csv(out_dir / "excluded_signals.csv", index=False)

    scores = assemble_scores(eligible_signals, config)
    scores.to_csv(out_dir / "scores.csv", index=False)

    print("eligible_signals rows:", len(eligible_signals))
    print("scores rows:", 0 if scores is None else len(scores))
    print("scores cols:", None if scores is None else list(scores.columns))

    if scores is None or (hasattr(scores, "empty") and scores.empty):
        raise RuntimeError("Scoring layer returned None or empty DataFrame. Check src/cde/scoring/assemble.py and individual score modules.")
    
    candidates = build_topic_candidates(eligible_signals, scores, config)
    recs = recommend_for_population(candidates, config)

    receipts = build_receipts(recs, candidates, eligible_signals, scores, config, excluded_signals=excluded_signals)
    export_run_artifacts(out_dir, auditor, recs, receipts, config, excluded_signals=excluded_signals)

    auditor.finish_run()
    print(f"Done. Wrote outputs to: {out_dir}")


if __name__ == "__main__":
    main()
