from __future__ import annotations

from typing import Any, Dict

import pandas as pd


def score_confidence(signals: pd.DataFrame, config: Dict[str, Any]) -> pd.DataFrame:
    """
    Confidence score: currently passes through the computed signal confidence.
    Can be replaced later with richer logic (data freshness, sample size, model certainty).
    """
    df = signals[["agent_id", "period", "call_type", "metric"]].copy()
    conf = pd.to_numeric(signals.get("confidence"), errors="coerce").fillna(0.5).clip(0.0, 1.0)
    df["confidence_score"] = conf.astype(float)
    return df
