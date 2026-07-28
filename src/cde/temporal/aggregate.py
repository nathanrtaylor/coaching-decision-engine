# src/cde/temporal/aggregate.py
from __future__ import annotations

from typing import Dict, Any, List
import numpy as np
import pandas as pd


DEFAULT_TEMPORAL_CONFIG: Dict[str, Any] = {
    # Windowing
    "window_weeks": 8,
    "period_col": "period",
    "value_col": "value",       # used for trend if gap not present / not used
    "gap_col": "gap",           # recommended for level/trend if your gap is “badness vs benchmark”
    "use_gap_for_level": True,
    "use_gap_for_trend": True,

    # Trend method
    "trend_method": "slope",    # "slope" or "last_minus_first"
    "min_weeks_for_trend": 3,   # avoid nonsense slopes on tiny samples

    # Confidence
    "confidence_method": "coverage",  # "coverage" or "coverage_x_stability"
    "stability_dampener": 1.0,        # higher = more dampening when volatility is high (only for coverage_x_stability)

    # Optional recency shift (last 2 vs prior 6)
    "include_recency_shift": True,
    "recent_weeks": 2,          # last N weeks in window considered "recent"

    # If your gap sign convention is opposite, flip here so + means “worse”
    # e.g., if negative gap means worse, set flip_gap_sign=True
    "flip_gap_sign": False,
}


def _merge_config(config: Dict[str, Any]) -> Dict[str, Any]:
    temporal = (config or {}).get("temporal", {}) if isinstance(config, dict) else {}
    merged = dict(DEFAULT_TEMPORAL_CONFIG)
    merged.update(temporal or {})
    return merged


def _coerce_datetime(s: pd.Series) -> pd.Series:
    # Period is expected to be week-ending date; we tolerate strings
    return pd.to_datetime(s, errors="coerce")


def _get_last_n_periods(df: pd.DataFrame, period_col: str, n: int) -> List[pd.Timestamp]:
    periods = _coerce_datetime(df[period_col]).dropna().unique()
    if len(periods) == 0:
        return []
    periods = np.sort(periods)  # ascending
    return list(periods[-n:])


def _safe_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _slope_over_time(x: np.ndarray, y: np.ndarray) -> float:
    """
    Compute slope of y ~ x via simple least squares.
    Returns 0.0 if degenerate.
    """
    if len(x) != len(y) or len(x) < 2:
        return 0.0

    x = x.astype(float)
    y = y.astype(float)

    # keep only finite y
    mask = np.isfinite(y) & np.isfinite(x)
    x2 = x[mask]
    y2 = y[mask]

    if len(x2) < 2 or np.nanstd(x2) == 0:
        return 0.0

    # slope = cov(x,y) / var(x)
    vx = np.var(x2)
    if vx == 0:
        return 0.0
    cov = np.mean((x2 - np.mean(x2)) * (y2 - np.mean(y2)))
    return float(cov / vx)


def aggregate_scores_window(
    eligible_signals: pd.DataFrame,
    config: Dict[str, Any],
) -> pd.DataFrame:
    """
    Collapse weekly eligible_signals into one row per agent_id × call_type × metric
    over the most recent N unique periods (default 8).

    Expected eligible_signals columns (minimum):
      - agent_id, period, call_type, metric
      - gap (recommended) and/or value

    Output columns:
      - agent_id, call_type, metric
      - window_start, window_end, weeks_present
      - level_8w, trend_8w, volatility_8w, confidence_8w
      - recency_shift (optional)
    """
    cols_out = [
        "agent_id",
        "call_type",
        "metric",
        "window_start",
        "window_end",
        "weeks_present",
        "level_8w",
        "trend_8w",
        "volatility_8w",
        "confidence_8w",
        "benchmark_8w",
        "direction",
    ]

    # Return empty with expected schema
    if eligible_signals is None or eligible_signals.empty:
        return pd.DataFrame(columns=cols_out + ["recency_shift"])

    cfg = _merge_config(config)

    period_col = cfg["period_col"]
    value_col = cfg["value_col"]
    gap_col = cfg["gap_col"]

    required = {"agent_id", period_col, "call_type", "metric"}
    missing_required = [c for c in required if c not in eligible_signals.columns]
    if missing_required:
        raise ValueError(f"aggregate_scores_window: missing required columns: {missing_required}")

    df = eligible_signals.copy()

    # Coerce period
    df[period_col] = _coerce_datetime(df[period_col])
    df = df[df[period_col].notna()]
    if df.empty:
        return pd.DataFrame(columns=cols_out + ["recency_shift"])

    # Choose which series drives level/trend/volatility
    use_gap_level = bool(cfg.get("use_gap_for_level", True)) and (gap_col in df.columns)
    use_gap_trend = bool(cfg.get("use_gap_for_trend", True)) and (gap_col in df.columns)

    # numeric conversions
    if gap_col in df.columns:
        df[gap_col] = _safe_numeric(df[gap_col])
        if cfg.get("flip_gap_sign", False):
            df[gap_col] = -df[gap_col]

    if value_col in df.columns:
        df[value_col] = _safe_numeric(df[value_col])

    # Window: last N unique periods globally (deterministic “latest completed week” behavior)
    window_weeks = int(cfg.get("window_weeks", 8))
    window_periods = _get_last_n_periods(df, period_col, window_weeks)
    if not window_periods:
        return pd.DataFrame(columns=cols_out + ["recency_shift"])

    df = df[df[period_col].isin(window_periods)].copy()
    if df.empty:
        return pd.DataFrame(columns=cols_out + ["recency_shift"])

    window_start = min(window_periods)
    window_end = max(window_periods)

    # Decide aggregation series
    level_series_name = gap_col if use_gap_level else value_col
    trend_series_name = gap_col if use_gap_trend else value_col

    if level_series_name not in df.columns:
        raise ValueError(
            f"aggregate_scores_window: missing '{level_series_name}' for level computation "
            f"(configure temporal.use_gap_for_level/use_gap_for_trend or ensure columns exist)"
        )
    if trend_series_name not in df.columns:
        raise ValueError(
            f"aggregate_scores_window: missing '{trend_series_name}' for trend computation "
            f"(configure temporal.use_gap_for_level/use_gap_for_trend or ensure columns exist)"
        )

    include_recency = bool(cfg.get("include_recency_shift", True))
    recent_weeks = int(cfg.get("recent_weeks", 2))
    recent_weeks = max(1, min(recent_weeks, window_weeks))

    # Precompute a stable week index within the window
    periods_sorted = sorted(window_periods)
    period_to_idx = {p: i for i, p in enumerate(periods_sorted)}
    df["_week_idx"] = df[period_col].map(period_to_idx).astype(float)

    trend_method = str(cfg.get("trend_method", "slope")).lower()
    min_weeks_for_trend = int(cfg.get("min_weeks_for_trend", 3))

    confidence_method = str(cfg.get("confidence_method", "coverage")).lower()
    stability_dampener = float(cfg.get("stability_dampener", 1.0))

    group_keys = ["agent_id", "call_type", "metric"]

    def _agg_one(g: pd.DataFrame) -> pd.Series:
        """
        NaN-safe aggregation:
        - weeks_present counts periods with finite level values
        - level/volatility computed only if finite values exist
        - trend computed on finite values only
        """
        # --- weeks_present: only weeks with usable datapoints for the level series
        lvl_series = g[level_series_name].astype(float)
        finite_lvl_mask = np.isfinite(lvl_series.values)
        weeks_present = int(g.loc[finite_lvl_mask, period_col].nunique())

        # --- level + volatility (NaN-safe)
        finite_lvl = lvl_series.values[finite_lvl_mask]
        if finite_lvl.size == 0:
            level_8w = 0.0
            volatility_8w = 0.0
        else:
            level_8w = float(finite_lvl.mean())
            volatility_8w = float(finite_lvl.std())

        # --- trend (NaN-safe)
        g2 = g.sort_values(period_col)
        x_all = g2["_week_idx"].astype(float).values
        y_all = g2[trend_series_name].astype(float).values
        finite_trend_mask = np.isfinite(x_all) & np.isfinite(y_all)
        x = x_all[finite_trend_mask]
        y = y_all[finite_trend_mask]

        if weeks_present < min_weeks_for_trend or y.size < 2:
            trend_8w = 0.0
        else:
            if trend_method == "last_minus_first":
                trend_8w = float(y[-1] - y[0])
            else:
                trend_8w = _slope_over_time(x, y)

        # --- confidence (based on weeks_present)
        coverage = weeks_present / float(window_weeks)
        if confidence_method == "coverage_x_stability":
            stability = 1.0 / (1.0 + stability_dampener * volatility_8w)
            confidence_8w = float(coverage * stability)
        else:
            confidence_8w = float(coverage)

        # --- benchmark (mean of finite benchmarks in window; constant per metric in practice)
        if "benchmark" in g.columns:
            bvals = pd.to_numeric(g["benchmark"], errors="coerce").values
            bvals = bvals[np.isfinite(bvals)]
            benchmark_8w = float(bvals.mean()) if bvals.size else float("nan")
        else:
            benchmark_8w = float("nan")

        # --- direction (constant per metric; carried so scoring can be direction-aware)
        if "direction" in g.columns and g["direction"].notna().any():
            direction = str(g["direction"].dropna().iloc[0])
        else:
            direction = "higher_is_better"

        out = {
            "window_start": window_start,
            "window_end": window_end,
            "weeks_present": weeks_present,
            "level_8w": level_8w,
            "trend_8w": trend_8w,
            "volatility_8w": volatility_8w,
            "confidence_8w": confidence_8w,
            "benchmark_8w": benchmark_8w,
            "direction": direction,
        }

        if include_recency:
            recent_periods = set(periods_sorted[-recent_weeks:])

            recent_vals = g2[g2[period_col].isin(recent_periods)][level_series_name].astype(float).values
            prior_vals = g2[~g2[period_col].isin(recent_periods)][level_series_name].astype(float).values

            recent_finite = recent_vals[np.isfinite(recent_vals)]
            prior_finite = prior_vals[np.isfinite(prior_vals)]

            if recent_finite.size == 0 or prior_finite.size == 0:
                out["recency_shift"] = 0.0
            else:
                out["recency_shift"] = float(recent_finite.mean() - prior_finite.mean())

        return pd.Series(out)

    agg = df.groupby(group_keys, dropna=False).apply(_agg_one).reset_index()

    # Ensure expected columns
    if include_recency and "recency_shift" not in agg.columns:
        agg["recency_shift"] = 0.0

    ordered = cols_out + (["recency_shift"] if include_recency else [])
    return agg[ordered]