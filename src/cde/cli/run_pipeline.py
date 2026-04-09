from __future__ import annotations

import argparse
from pathlib import Path

from cde.governance.audit import RunAuditor
from cde.governance.versioning import resolve_active_config, resolve_raw_export_dir
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
from cde.temporal.aggregate import aggregate_scores_window


def main() -> None:
    parser = argparse.ArgumentParser(description="Run end-to-end Coaching Decision Engine pipeline.")
    parser.add_argument(
        "--raw-dir",
        type=str,
        default=None,
        help="Raw export folder (e.g. data/raw/weekly/2026-02-16). "
        "If omitted, resolved from data_snapshot in configs/active.yaml.",
    )
    parser.add_argument("--out-dir", type=str, required=True, help="Path to outputs/runs/<timestamp> folder to write artifacts")
    parser.add_argument("--configs-dir", type=str, default="configs", help="Path to configs directory")
    parser.add_argument("--run-id", type=str, default=None, help="Optional run id (otherwise derived by auditor)")
    parser.add_argument(
        "--write-point-in-time-scores",
        action="store_true",
        help="Write scores.csv (per-period point-in-time scores). Recommendations use scores_windowed.csv only.",
    )
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    configs_dir = Path(args.configs_dir)

    config = resolve_active_config(configs_dir)
    raw_dir = Path(args.raw_dir) if args.raw_dir else resolve_raw_export_dir(configs_dir, config)

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

    # --- Normalize period dtype for deterministic merges ---
    import pandas as pd

    eligible_signals["period"] = pd.to_datetime(
        eligible_signals["period"], errors="coerce"
    )

    # excluded_signals can be empty (no exclusions). In that case pandas creates a df with no columns.
    if excluded_signals is not None and not excluded_signals.empty:
        # support either canonical 'period' or legacy 'week_ending'
        if "period" not in excluded_signals.columns and "week_ending" in excluded_signals.columns:
            excluded_signals = excluded_signals.rename(columns={"week_ending": "period"})

        if "period" in excluded_signals.columns:
            excluded_signals["period"] = pd.to_datetime(excluded_signals["period"], errors="coerce")
    else:
        # force a well-formed empty df with expected columns so downstream writes don't break
        excluded_signals = pd.DataFrame(columns=["agent_id", "period", "call_type", "metric", "reason"])

    scores = assemble_scores(eligible_signals, config)
    if args.write_point_in_time_scores:
        scores.to_csv(out_dir / "scores.csv", index=False)

    print("eligible_signals rows:", len(eligible_signals))
    print("scores rows:", 0 if scores is None else len(scores))
    print("scores cols:", None if scores is None else list(scores.columns))

    if scores is None or (hasattr(scores, "empty") and scores.empty):
        raise RuntimeError("Scoring layer returned None or empty DataFrame. Check src/cde/scoring/assemble.py and individual score modules.")
    
    # --- NEW: 8-week windowed aggregation for "next coaching" decision grain ---
    windowed = aggregate_scores_window(eligible_signals=eligible_signals, config=config)
    windowed.to_csv(out_dir / "scores_windowed_raw.csv", index=False)

    # Build a "scores-like" table for downstream modules (candidate builder / receipts)
    # - keep join keys aligned
    # - provide score_* columns the engine expects
    scores_windowed = windowed.rename(columns={
        "level_8w": "score_level",
        "trend_8w": "score_trend",
        "confidence_8w": "score_confidence",
        # proxy: treat volatility as a risk signal for now (good enough for a first pass)
        "volatility_8w": "score_risk",
    }).copy()

    # Many downstream joins expect a 'period' column; set it to the window_end (latest week in the window)
    scores_windowed["period"] = scores_windowed["window_end"]

    # If downstream expects score_total, compute a deterministic placeholder
    # (You can replace this later with a more principled composition.)
    scores_windowed["score_total"] = (
        scores_windowed["score_level"].fillna(0.0)
        + scores_windowed["score_trend"].fillna(0.0)
        + scores_windowed["score_risk"].fillna(0.0)
    ) * scores_windowed["score_confidence"].fillna(0.0)

    scores_windowed.to_csv(out_dir / "scores_windowed.csv", index=False)

    candidates = build_topic_candidates(eligible_signals, scores_windowed, config)
    recs = recommend_for_population(candidates, config)

    receipts = build_receipts(recs, candidates, eligible_signals, scores_windowed, config, excluded_signals=excluded_signals)
    export_run_artifacts(out_dir, auditor, recs, receipts, config, excluded_signals=excluded_signals)

    auditor.finish_run()
    print(f"Done. Wrote outputs to: {out_dir}")


if __name__ == "__main__":
    main()
