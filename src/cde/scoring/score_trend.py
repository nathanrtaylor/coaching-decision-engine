# src/cde/scoring/score_trend.py
from typing import Dict, Any
import pandas as pd
import numpy as np

def score_trend(signals: pd.DataFrame, config: Dict[str, Any]) -> pd.DataFrame:
    cols = ["agent_id","period","call_type","metric","score_trend"]
    if signals is None or signals.empty:
        return pd.DataFrame(columns=cols)
    df = signals.copy()
    df["score_trend"] = (pd.to_numeric(df.get("trend"), errors="coerce").abs()).fillna(0.0)
    return df[["agent_id","period","call_type","metric","score_trend"]]
