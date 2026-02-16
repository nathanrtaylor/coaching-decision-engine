from __future__ import annotations

from typing import Any, Dict

import numpy as np
import pandas as pd


def score_risk(signals: pd.DataFrame, level: pd.DataFrame, trend: pd.DataFrame, config: Dict[str, Any]) -> pd.DataFrame:
    """
    Risk/Urgency score: combines level+trend but keeps them separate upstream.
    This is NOT the final blended score; it is a third axis used in prioritization.
    """
    df = signals[["agent_id", "period", "call_type", "metric"]].copy()
    df = df.merge(level, on=["agent_id", "period", "call_type", "metric"], how="left")
    df = df.merge(trend, on=["agent_id", "period", "call_type", "metric"], how="left")

    a = float((config.get("risk_model") or {}).get("alpha_level", 0.7))
    b = float((config.get("risk_model") or {}).get("beta_trend", 0.3))

    risk = a * df["level_score"].fillna(0.0) + b * df["trend_score"].fillna(0.0)
    df["risk_score"] = risk.clip(0.0, 1.0).astype(float)
    return df
