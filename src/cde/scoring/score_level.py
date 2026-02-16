from __future__ import annotations

from typing import Any, Dict

import numpy as np
import pandas as pd


def score_level(signals: pd.DataFrame, config: Dict[str, Any]) -> pd.DataFrame:
    """
    Level score: how 'bad' is the current level relative to benchmark (if available),
    oriented so higher score = more coaching opportunity.

    Output: columns [agent_id, period, call_type, metric, level_score]
    """
    df = signals.copy()

    # If gap exists, use it; else z-score across population at that period+call_type
    if "gap" in df.columns and df["gap"].notna().any():
        raw = df["gap"].astype(float)
    else:
        grp = df.groupby(["period", "call_type", "metric"])["value"]
        mean = grp.transform("mean")
        std = grp.transform("std").replace(0, np.nan)
        raw = (df["value"] - mean) / std

    # Make sure "worse" becomes higher
    direction = df.get("direction", "higher_is_better")
    worse = raw.copy()
    worse = np.where(direction == "higher_is_better", -worse, worse)

    # squash to [0,1] via logistic
    level_score = 1 / (1 + np.exp(-pd.Series(worse).fillna(0.0)))
    out = df[["agent_id", "period", "call_type", "metric"]].copy()
    out["level_score"] = level_score.astype(float)
    return out
