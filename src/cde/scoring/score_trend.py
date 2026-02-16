from __future__ import annotations

from typing import Any, Dict

import numpy as np
import pandas as pd


def score_trend(signals: pd.DataFrame, config: Dict[str, Any]) -> pd.DataFrame:
    """
    Trend score: penalize deteriorating trends (worse getting worse) as higher score.
    Uses pct change already computed as 'trend'.
    """
    df = signals.copy()
    t = pd.to_numeric(df.get("trend"), errors="coerce").fillna(0.0)

    # For higher_is_better, negative trend is bad; for lower_is_better, positive trend is bad
    direction = df.get("direction", "higher_is_better")
    bad_trend = np.where(direction == "higher_is_better", -t, t)

    # squash to [0,1]
    trend_score = 1 / (1 + np.exp(-bad_trend))
    out = df[["agent_id", "period", "call_type", "metric"]].copy()
    out["trend_score"] = trend_score.astype(float)
    return out
