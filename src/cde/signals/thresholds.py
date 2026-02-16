from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class ThresholdResult:
    eligible_signals: pd.DataFrame
    excluded_signals: pd.DataFrame


def apply_signal_thresholds(signals: pd.DataFrame, config: Dict[str, Any]) -> ThresholdResult:
    """
    Apply deterministic signal gating using configs/thresholds/signal_thresholds.yaml (loaded into config["thresholds"]).

    Returns:
      - eligible_signals: only signals that pass gates
      - excluded_signals: signals that failed with reason codes (for receipts/audit)
    """
    thr = (config.get("thresholds") or {}).get("signal_thresholds") or {}
    if not thr:
        # If no thresholds configured, treat everything as eligible (not recommended)
        eligible = signals.copy()
        excluded = signals.iloc[0:0].copy()
        excluded["exclusion_reasons"] = []
        return ThresholdResult(eligible_signals=eligible, excluded_signals=excluded)

    sig = signals.copy()

    # Ensure required columns exist
    required_cols = {"agent_id", "period", "call_type", "metric", "value", "trend", "confidence", "volatility", "direction"}
    missing = required_cols - set(sig.columns)
    if missing:
        raise ValueError(f"Signals missing required cols for thresholding: {sorted(missing)}")

    # Compute a distribution z-score (used when benchmark gap isn't available)
    # z is computed within (period, call_type, metric)
    grp = sig.groupby(["period", "call_type", "metric"])["value"]
    mean = grp.transform("mean")
    std = grp.transform("std").replace(0, np.nan)
    sig["_z_raw"] = (sig["value"] - mean) / std
    # orient so "worse" => higher
    sig["_z_bad"] = np.where(sig["direction"] == "higher_is_better", -sig["_z_raw"], sig["_z_raw"])
    sig["_z_bad"] = pd.to_numeric(sig["_z_bad"], errors="coerce")

    # Determine category per metric if metric_catalog is loaded (recommended)
    metric_catalog = (config.get("metric_catalog") or {}).get("metric_catalog") or (config.get("metric_catalog") or {})
    metrics_meta = (metric_catalog.get("metrics") or {}) if isinstance(metric_catalog, dict) else {}
    sig["_category"] = sig["metric"].map(lambda m: (metrics_meta.get(m) or {}).get("category", "unknown"))

    excluded_rows = []
    eligible_mask = []

    for idx, row in sig.iterrows():
        metric = row["metric"]
        call_type = row.get("call_type")
        category = row["_category"]

        # Resolve thresholds with precedence: by_metric -> by_call_type+category -> by_category -> global
        t = _resolve_thresholds(thr, metric=metric, call_type=call_type, category=category)

        reasons = []

        # ---- Confidence gate
        conf = _to_float(row.get("confidence"))
        if conf is None or conf < _to_float(t.get("min_confidence"), default=0.0):
            reasons.append("LOW_CONFIDENCE")

        # ---- Volatility gate (if volatility present)
        vol = _to_float(row.get("volatility"))
        max_vol = _to_float(t.get("max_volatility"))
        if max_vol is not None and vol is not None and vol > max_vol:
            reasons.append("HIGH_VOLATILITY")

        # ---- Denominator gate (if present in signals; optional)
        # If you keep denom/numer in signals, you can wire this; otherwise rely on confidence.
        denom_min = _to_float(t.get("min_denominator_default"))
        if denom_min is not None and "denominator" in sig.columns:
            denom = _to_float(row.get("denominator"))
            if denom is not None and denom < denom_min:
                reasons.append("LOW_DENOMINATOR")

        # ---- Reference point requirement
        require_ref = bool((thr.get("candidate_rules") or {}).get("require_reference_point", True))
        gap = _to_float(row.get("gap"))
        z_bad = _to_float(row.get("_z_bad"))
        if require_ref and gap is None and z_bad is None:
            reasons.append("NO_REFERENCE_POINT")

        # ---- Magnitude gate
        require_bad_mag = bool((thr.get("candidate_rules") or {}).get("require_bad_magnitude", True))
        if require_bad_mag:
            mag_pass = _magnitude_pass(row=row, t=t)
            if not mag_pass:
                reasons.append("INSUFFICIENT_MAGNITUDE")

        # ---- Trend gate
        require_bad_trend = bool((thr.get("candidate_rules") or {}).get("require_bad_trend", False))
        only_worsening = bool((thr.get("candidate_rules") or {}).get("only_worsening", False))

        trend = _to_float(row.get("trend"))  # pct change; bad direction depends on direction
        bad_trend_pct = _to_float(t.get("min_bad_trend_pct"))
        bad_trend = _is_bad_trend(trend=trend, direction=row.get("direction"), min_bad_trend_pct=bad_trend_pct)

        if require_bad_trend and not bad_trend:
            reasons.append("INSUFFICIENT_BAD_TREND")

        if only_worsening and not bad_trend:
            reasons.append("NOT_WORSENING")

        passed = (len(reasons) == 0)
        eligible_mask.append(passed)

        if not passed:
            excluded_rows.append(
                {
                    "agent_id": row["agent_id"],
                    "period": row["period"],
                    "call_type": row["call_type"],
                    "metric": metric,
                    "category": category,
                    "value": _to_float(row.get("value")),
                    "gap": gap,
                    "z_bad": z_bad,
                    "trend": trend,
                    "confidence": conf,
                    "volatility": vol,
                    "exclusion_reasons": reasons,
                }
            )

    eligible = sig[pd.Series(eligible_mask, index=sig.index)].copy()
    excluded = pd.DataFrame(excluded_rows)

    # cleanup internal columns
    eligible = eligible.drop(columns=[c for c in ["_z_raw", "_z_bad", "_category"] if c in eligible.columns], errors="ignore")

    return ThresholdResult(eligible_signals=eligible, excluded_signals=excluded)


def _resolve_thresholds(thr: Dict[str, Any], metric: str, call_type: Optional[str], category: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {}

    # global
    out.update(thr.get("global") or {})

    # by_category
    by_cat = thr.get("by_category") or {}
    if category in by_cat:
        out.update(by_cat[category] or {})

    # by_call_type
    by_ct = thr.get("by_call_type") or {}
    if call_type and call_type in by_ct:
        ct_block = by_ct[call_type] or {}
        if isinstance(ct_block, dict) and category in ct_block:
            out.update(ct_block[category] or {})

    # by_metric (highest precedence)
    by_metric = thr.get("by_metric") or {}
    if metric in by_metric:
        out.update(by_metric[metric] or {})

    return out


def _magnitude_pass(row: pd.Series, t: Dict[str, Any]) -> bool:
    """
    If benchmark gap exists, compare abs(gap) to min_abs_gap_from_benchmark.
    Else use z_bad >= min_bad_z (distribution severity).
    """
    gap = _to_float(row.get("gap"))
    min_gap = _to_float(t.get("min_abs_gap_from_benchmark"))
    if gap is not None and min_gap is not None:
        # IMPORTANT: gap is signed; we care about "badness", not absolute deviation
        # If direction is higher_is_better, negative gap is bad; if lower_is_better, positive gap is bad.
        direction = row.get("direction")
        bad_gap = -gap if direction == "higher_is_better" else gap
        return bad_gap >= min_gap

    z_bad = _to_float(row.get("_z_bad"))
    min_bad_z = _to_float(t.get("min_bad_z"))
    if z_bad is not None and min_bad_z is not None:
        return z_bad >= min_bad_z

    # If no magnitude rule applicable, fail closed (prevents accidental candidacy)
    return False


def _is_bad_trend(trend: Optional[float], direction: Optional[str], min_bad_trend_pct: Optional[float]) -> bool:
    if trend is None or min_bad_trend_pct is None:
        return False
    # trend is pct change; for higher_is_better, negative is bad; for lower_is_better, positive is bad
    bad = (-trend) if direction == "higher_is_better" else trend
    return bad >= min_bad_trend_pct


def _to_float(x: Any, default: Optional[float] = None) -> Optional[float]:
    if x is None:
        return default
    try:
        if isinstance(x, float) and pd.isna(x):
            return default
        return float(x)
    except Exception:
        return default
