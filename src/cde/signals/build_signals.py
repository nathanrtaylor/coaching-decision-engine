# src/cde/signals/build_signals.py

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import numpy as np
import pandas as pd

from cde.signals.benchmarks import get_benchmark_value, benchmark_gap
from cde.utils.logging import get_logger
from typing import Any, Optional
from cde.signals.load_inputs import load_normalized_for_signals

log = get_logger(__name__)


def _unwrap_root(cfg: Dict[str, Any], root_key: str) -> Dict[str, Any]:
    """
    Supports either shape:
      - cfg[root_key] == {root_key: {...}}  (recommended)
      - cfg[root_key] == {...}              (already unwrapped)
    Returns the inner dict.
    """
    block = cfg.get(root_key) or {}
    if isinstance(block, dict) and root_key in block and isinstance(block[root_key], dict):
        return block[root_key]
    return block if isinstance(block, dict) else {}


def _to_float(x: Any) -> Optional[float]:
    if x is None:
        return None
    try:
        if isinstance(x, float) and pd.isna(x):
            return None
        return float(x)
    except Exception:
        return None


def _safe_pct_change(curr: Optional[float], prev: Optional[float]) -> Optional[float]:
    if curr is None or prev is None:
        return None
    if prev == 0:
        return None
    return float((curr - prev) / abs(prev))


def _compute_value_row(
    numerator: Optional[float],
    denominator: Optional[float],
    calculation: Optional[str],
    raw_value: Optional[float],
    prefer_value: bool,
    default_calculation: Optional[str],
    handlers: Dict[str, Any],
) -> Optional[float]:
    """
    Deterministic computation:
      - if prefer_value and raw_value present -> use raw_value
      - else compute from numerator/denominator based on calculation or default_calculation
    """
    if prefer_value and raw_value is not None:
        return raw_value

    calc = calculation or default_calculation
    if not calc:
        return raw_value  # last resort

    calc = str(calc).strip().lower()
    handler = handlers.get(calc) or {}

    # supported patterns: rate/avg = numerator/denominator; sum/count/score = numerator
    if calc in ("rate", "avg"):
        if numerator is None or denominator is None:
            return None
        denom_min = _to_float(handler.get("denominator_min")) or 1.0
        if denominator < denom_min or denominator == 0:
            return None
        return float(numerator / denominator)

    if calc in ("sum", "count", "score"):
        return numerator

    # unknown calc => fall back to raw value if present
    return raw_value

def build_signals(normalized: Dict[str, pd.DataFrame], config: Dict[str, Any]) -> pd.DataFrame:
    """
    Build long-form signals by UNION-ing multiple tall-skinny sources as defined in:
      - config["source_catalog"] (sources + schemas + computation rules)
      - config["metric_catalog"] (canonical metrics + source bindings + direction/category/benchmark)

    Call type "off switch":
      If config["call_type_mode"] == "disabled", then call_type is collapsed to
      config["default_call_type"] (default: "all_calls"), and all call-type specific
      segmentation/benchmarks/overrides operate in that single bucket.

    Output columns (opinionated):
      agent_id, period, call_type, metric, category, direction,
      source, source_metric_key,
      numerator, denominator, calculation, value,
      prev_value, trend, volatility, confidence,
      benchmark, gap
    """
    source_catalog = _unwrap_root(config, "source_catalog")
    metric_catalog = _unwrap_root(config, "metric_catalog")

    sources_cfg = (source_catalog.get("sources") or {})
    metrics_cfg = (metric_catalog.get("metrics") or {})
    governance = (metric_catalog.get("governance") or {})
    disallow_unknown = bool(governance.get("disallow_unknown_metrics", True))

    if not sources_cfg:
        raise ValueError("source_catalog.sources is empty or missing.")
    if not metrics_cfg:
        raise ValueError("metric_catalog.metrics is empty or missing.")

    call_type_mode = config.get("call_type_mode", "enabled")
    default_call_type = config.get("default_call_type", "all_calls")

    # Build mapping from (source, source_metric_key) -> canonical metric name
    source_key_to_metric: Dict[Tuple[str, str], str] = {}
    metric_meta: Dict[str, Dict[str, Any]] = {}
    for canonical_metric, m in metrics_cfg.items():
        src = m.get("source")
        key = m.get("source_metric_key")
        if not src or not key:
            raise ValueError(f"Metric '{canonical_metric}' missing source or source_metric_key in metric_catalog.")
        source_key_to_metric[(str(src), str(key))] = canonical_metric
        metric_meta[canonical_metric] = m

    # Union all sources into one standardized long table
    frames = []
    for source_name, s in sources_cfg.items():
        if source_name not in normalized:
            log.info("Source table '%s' not found in normalized inputs; skipping.", source_name)
            continue

        df = normalized[source_name].copy()

        schema = (s.get("schema") or {})

        # ✅ Skip dimension/non-metric sources (e.g., agents)
        if (s.get("type") == "dimension") or (schema.get("metric_key") in (None, "null", "")):
            log.info("Skipping non-metric source '%s' in build_signals()", source_name)
            continue
        
        entity_keys = (schema.get("entity_keys") or {})
        agent_col = entity_keys.get("agent_id", "agent_id")
        period_col = entity_keys.get("period", "week_start")
        call_type_col = entity_keys.get("call_type", "call_type")

        metric_key_col = schema.get("metric_key")
        num_col = schema.get("numerator")
        den_col = schema.get("denominator")
        calc_col = schema.get("calculation")
        val_col = schema.get("value")

        if not metric_key_col:
            raise ValueError(f"Source '{source_name}' missing schema.metric_key in source_catalog.")

        # Create standardized columns
        out = pd.DataFrame()
        out["agent_id"] = df[agent_col]
        out["period"] = df[period_col]

        if call_type_col in df.columns:
            out["call_type"] = df[call_type_col]
        else:
            out["call_type"] = None

        # Call type off switch: collapse all call types into one bucket
        if call_type_mode == "disabled":
            out["call_type"] = default_call_type

        out["source"] = source_name
        out["source_metric_key"] = df[metric_key_col].astype(str)

        out["numerator"] = pd.to_numeric(df[num_col], errors="coerce") if num_col and num_col in df.columns else np.nan
        out["denominator"] = pd.to_numeric(df[den_col], errors="coerce") if den_col and den_col in df.columns else np.nan

        out["calculation"] = df[calc_col] if calc_col and calc_col in df.columns else None
        out["value_raw"] = pd.to_numeric(df[val_col], errors="coerce") if val_col and val_col in df.columns else np.nan

        frames.append(out)

    if not frames:
        raise ValueError("No source tables were found/loaded. Check normalized inputs and source_catalog.yaml.")

    base = pd.concat(frames, ignore_index=True)

    # --------------------------------------------------
    # Enrich with org fields from agents.csv (if present)
    # --------------------------------------------------

    agents_raw = normalized.get("agents")

    if agents_raw is not None and not agents_raw.empty:

        agents = agents_raw.copy()

        # Standardize to canonical keys
        agents["agent_id"] = agents["agent_id"].astype(str)
        agents["period"] = agents["week_ending"]

        agents = agents.drop_duplicates(["agent_id", "period"])

        # Ensure base keys are strings for safe join
        base["agent_id"] = base["agent_id"].astype(str)

        base = base.merge(
            agents[["agent_id", "period", "mascot", "icp_client", "coach", "coach_id"]],
            on=["agent_id", "period"],
            how="left"
        )


    # Map to canonical metric names
    base["metric"] = [
        source_key_to_metric.get((src, key))
        for src, key in zip(base["source"].tolist(), base["source_metric_key"].tolist())
    ]

    if disallow_unknown:
        base = base[base["metric"].notna()].copy()
    else:
        base["metric"] = base["metric"].fillna(base["source_metric_key"])

    # Attach category, direction, benchmark lookup key
    base["category"] = base["metric"].map(lambda m: (metric_meta.get(m) or {}).get("category"))
    base["direction"] = base["metric"].map(lambda m: (metric_meta.get(m) or {}).get("direction", "higher_is_better"))
    base["benchmark_key"] = base["metric"].map(
        lambda m: ((metric_meta.get(m) or {}).get("benchmark") or {}).get("key", m)
    )

    # Compute value deterministically per source computation rules (with per-metric overrides)
    computed_vals = []
    for _, row in base.iterrows():
        src = row["source"]
        metric = row["metric"]

        s_cfg = sources_cfg.get(src) or {}
        comp = (s_cfg.get("computation") or {})

        prefer_value = bool(comp.get("prefer_value_column_if_present", True))
        default_calc = comp.get("default_calculation")
        handlers = comp.get("calculation_handlers") or {}

        # allow per-metric expected_calculation override to set default_calc if source calc missing
        m_over = (metric_meta.get(metric) or {}).get("computation_override") or {}
        expected_calc = m_over.get("expected_calculation")
        calculation = row.get("calculation")
        calculation = None if (isinstance(calculation, float) and pd.isna(calculation)) else calculation
        if expected_calc and (calculation is None or str(calculation).strip() == ""):
            default_calc = expected_calc

        numerator = _to_float(row.get("numerator"))
        denominator = _to_float(row.get("denominator"))
        raw_value = _to_float(row.get("value_raw"))

        v = _compute_value_row(
            numerator=numerator,
            denominator=denominator,
            calculation=str(calculation).strip().lower() if calculation is not None else None,
            raw_value=raw_value,
            prefer_value=prefer_value,
            default_calculation=str(default_calc).strip().lower() if default_calc is not None else None,
            handlers=handlers,
        )
        computed_vals.append(v)

    base["value"] = computed_vals

    # Sort for time-based calculations
    base = base.sort_values(["agent_id", "call_type", "metric", "period"]).reset_index(drop=True)

    # Previous value and trend
    base["prev_value"] = base.groupby(["agent_id", "call_type", "metric"])["value"].shift(1)
    base["trend"] = [
        _safe_pct_change(c, p)
        for c, p in zip(base["value"].tolist(), base["prev_value"].tolist())
    ]

    # Volatility: rolling std over last N periods (per agent+call_type+metric)
    window = int((config.get("signal_window") or {}).get("volatility_periods", 4))
    base["volatility"] = (
        base.groupby(["agent_id", "call_type", "metric"])["value"]
        .rolling(window, min_periods=2)
        .std()
        .reset_index(level=[0, 1, 2], drop=True)
    )

    # Benchmark + gap (benchmarks are looked up by benchmark_key; call_type is collapsed if disabled)
    base["benchmark"] = [
        get_benchmark_value(bkey, ct, config)
        for bkey, ct in zip(base["benchmark_key"].tolist(), base["call_type"].tolist())
    ]
    base["gap"] = [
        benchmark_gap(v, b) if v is not None and (b is not None) else None
        for v, b in zip(base["value"].tolist(), base["benchmark"].tolist())
    ]

    # Confidence (deterministic, explainable):
    # - present factor (value exists)
    # - denominator factor (if denom exists) using per-metric override > source default > global default
    # - volatility penalty (normalized within period+call_type+metric)
    present = (~pd.isna(pd.to_numeric(base["value"], errors="coerce"))).astype(float)

    # denominator floor: global default for confidence (not gating; gating happens in thresholds)
    global_den_min = float(
        (((config.get("thresholds") or {}).get("signal_thresholds") or {}).get("global") or {}).get(
            "min_denominator_default", 10
        )
    )

    src_default_den = {}
    for src_name, s_cfg in sources_cfg.items():
        dq = (s_cfg.get("data_quality") or {})
        src_default_den[src_name] = float(dq.get("default_denominator_min", global_den_min))

    per_metric_den_min = {}
    for m, meta in metric_meta.items():
        over = meta.get("computation_override") or {}
        if "denominator_min" in over:
            per_metric_den_min[m] = float(over["denominator_min"])

    denom_vals = pd.to_numeric(base["denominator"], errors="coerce")
    denom_min_vals = []
    for src, m in zip(base["source"].tolist(), base["metric"].tolist()):
        denom_min_vals.append(per_metric_den_min.get(m, src_default_den.get(src, global_den_min)))
    denom_min_vals = pd.Series(denom_min_vals, index=base.index)

    denom_factor = pd.Series(1.0, index=base.index)
    has_denom = denom_vals.notna()
    denom_factor.loc[has_denom] = (denom_vals.loc[has_denom] / denom_min_vals.loc[has_denom]).clip(lower=0.0, upper=1.0)

    # volatility normalization within (period, call_type, metric)
    vol = pd.to_numeric(base["volatility"], errors="coerce")
    vol_grp = base.groupby(["period", "call_type", "metric"])["volatility"]
    vol_mean = vol_grp.transform("mean")
    vol_std = vol_grp.transform("std").replace(0, np.nan)
    vol_z = (vol - vol_mean) / vol_std
    vol_z = pd.to_numeric(vol_z, errors="coerce").fillna(0.0)
    vol_penalty = (1 / (1 + np.exp(-vol_z))).clip(0.0, 1.0)
    vol_factor = (1.0 - 0.5 * vol_penalty).clip(0.0, 1.0)

    base["confidence"] = (present * (0.6 * denom_factor + 0.4 * vol_factor)).clip(0.0, 1.0)

    # Final column selection
    keep_cols = [
        "agent_id",
        "period",
        "mascot",
        "icp_client",
        "coach",
        "coach_id",
        "call_type",
        "category",
        "direction",
        "source",
        "metric",
        "numerator",
        "denominator",
        "calculation",
        "value",
        "prev_value",
        "trend",
        "volatility",
        "confidence",
        "benchmark",
        "gap",
    ]
    out = base[keep_cols].copy()

    return out