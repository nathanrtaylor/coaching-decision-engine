from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class ThresholdResult:
    eligible_signals: pd.DataFrame
    excluded_signals: pd.DataFrame


def apply_signal_thresholds(signals: pd.DataFrame, config: Dict[str, Any]) -> ThresholdResult:
    """
    Apply deterministic signal gating using configs/thresholds/signal_thresholds.yaml (loaded into config["thresholds"]).

    Adds a governed mode switch:
      - mode: "development" => minimal gating (value present + IDs; skips reference/magnitude/trend gates)
      - mode: "production"  => enforce reference/magnitude/trend rules (fail-closed)
    """
    thr = (config.get("thresholds") or {}).get("signal_thresholds") or {}
    if not thr:
        # If no thresholds configured, treat everything as eligible (not recommended)
        eligible = signals.copy()
        excluded = signals.iloc[0:0].copy()
        excluded["exclusion_reasons"] = []
        return ThresholdResult(eligible_signals=eligible, excluded_signals=excluded)

    mode = str(thr.get("mode", "production")).lower().strip()  # development | production

    sig = signals.copy()

    # ---- Required columns: minimal set differs by mode
    # Development mode should not require benchmark-derived fields.
    required_min = {"agent_id", "period", "call_type", "metric", "value", "direction"}
    required_prod = required_min | {"confidence"}  # production enforces confidence by default; can be overridden

    required_cols = required_min if mode == "development" else required_prod
    missing = required_cols - set(sig.columns)
    if missing:
        raise ValueError(f"Signals missing required cols for thresholding ({mode}): {sorted(missing)}")

    # Ensure optional columns exist so later logic doesn't KeyError
    # (These may be entirely null early on; that's okay.)
    for optional in ["trend", "confidence", "volatility", "gap", "denominator"]:
        if optional not in sig.columns:
            sig[optional] = np.nan

    # ---- Compute a distribution z-score (used when benchmark gap isn't available)
    # z is computed within (period, call_type, metric)
    # Note: if a group has std==0 or <2 rows, z will be NaN.
    grp = sig.groupby(["period", "call_type", "metric"])["value"]
    mean = grp.transform("mean")
    std = grp.transform("std").replace(0, np.nan)
    sig["_z_raw"] = (sig["value"] - mean) / std
    # orient so "worse" => higher
    sig["_z_bad"] = np.where(sig["direction"] == "higher_is_better", -sig["_z_raw"], sig["_z_raw"])
    sig["_z_bad"] = pd.to_numeric(sig["_z_bad"], errors="coerce")

    # ---- Determine category per metric if metric_catalog is loaded (recommended)
    metric_catalog = (config.get("metric_catalog") or {}).get("metric_catalog") or (config.get("metric_catalog") or {})
    metrics_meta = (metric_catalog.get("metrics") or {}) if isinstance(metric_catalog, dict) else {}
    sig["_category"] = sig["metric"].map(lambda m: (metrics_meta.get(m) or {}).get("category", "unknown"))

    excluded_rows = []
    eligible_mask = []

    # Candidate rules (global) — production defaults are "fail closed"
    candidate_rules = thr.get("candidate_rules") or {}

    require_ref = bool(candidate_rules.get("require_reference_point", True))
    require_bad_mag = bool(candidate_rules.get("require_bad_magnitude", True))
    require_bad_trend = bool(candidate_rules.get("require_bad_trend", False))
    only_worsening = bool(candidate_rules.get("only_worsening", False))

    # Development mode: relax gates that depend on benchmarks/history.
    if mode == "development":
        require_ref = False
        require_bad_mag = False
        require_bad_trend = False
        only_worsening = False

    for _, row in sig.iterrows():
        metric = row["metric"]
        call_type = row.get("call_type")
        category = row.get("_category", "unknown")

        # Resolve thresholds with precedence: by_metric -> by_call_type+category -> by_category -> global
        t = _resolve_thresholds(thr, metric=metric, call_type=call_type, category=category)

        reasons = []

        # ---- Basic value presence gate (both modes)
        val = _to_float(row.get("value"))
        if val is None:
            reasons.append("MISSING_VALUE")

        # ---- Confidence gate
        conf = _to_float(row.get("confidence"))
        min_conf = _to_float(t.get("min_confidence"), default=0.0)
        if conf is None:
            # In development, missing confidence should not block early runs.
            if mode != "development" and min_conf > 0.0:
                reasons.append("MISSING_CONFIDENCE")
        else:
            if conf < min_conf:
                reasons.append("LOW_CONFIDENCE")

        # ---- Volatility gate (optional; usually only meaningful with history)
        vol = _to_float(row.get("volatility"))
        max_vol = _to_float(t.get("max_volatility"))
        if max_vol is not None and vol is not None and vol > max_vol:
            reasons.append("HIGH_VOLATILITY")

        # ---- Denominator gate (optional; protects against tiny samples)
        denom_min = _to_float(t.get("min_denominator_default"))
        denom = _to_float(row.get("denominator"))
        if denom_min is not None and denom is not None and denom < denom_min:
            reasons.append("LOW_DENOMINATOR")

        # ---- Reference point requirement (production only unless explicitly enabled in dev)
        gap = _to_float(row.get("gap"))
        z_bad = _to_float(row.get("_z_bad"))
        if require_ref and gap is None and z_bad is None:
            reasons.append("NO_REFERENCE_POINT")

        # ---- Magnitude gate (production only unless explicitly enabled in dev)
        if require_bad_mag:
            mag_pass = _magnitude_pass(row=row, t=t)
            if not mag_pass:
                reasons.append("INSUFFICIENT_MAGNITUDE")

        # ---- Trend gate (production only unless explicitly enabled in dev)
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
                    "agent_id": row.get("agent_id"),
                    "period": row.get("period"),
                    "call_type": row.get("call_type"),
                    "metric": metric,
                    "category": category,
                    "value": val,
                    "gap": gap,
                    "z_bad": z_bad,
                    "trend": trend,
                    "confidence": conf,
                    "volatility": vol,
                    "exclusion_reasons": reasons,
                    "threshold_mode": mode,
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
    If benchmark gap exists, compare "bad_gap" to min_abs_gap_from_benchmark.
    Else use z_bad >= min_bad_z (distribution severity).
    """
    gap = _to_float(row.get("gap"))
    min_gap = _to_float(t.get("min_abs_gap_from_benchmark"))
    if gap is not None and min_gap is not None:
        direction = row.get("direction")
        bad_gap = -gap if direction == "higher_is_better" else gap
        return bad_gap >= min_gap

    z_bad = _to_float(row.get("_z_bad"))
    min_bad_z = _to_float(t.get("min_bad_z"))
    if z_bad is not None and min_bad_z is not None:
        return z_bad >= min_bad_z

    # Fail closed in production when magnitude is required and no reference is available
    return False


def _is_bad_trend(trend: Optional[float], direction: Optional[str], min_bad_trend_pct: Optional[float]) -> bool:
    if trend is None or min_bad_trend_pct is None:
        return False
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
