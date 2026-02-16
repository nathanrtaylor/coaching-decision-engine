# src/cde/scoring/score_risk.py
from typing import Dict, Any
import pandas as pd
import numpy as np

def score_risk(signals: pd.DataFrame, config: Dict[str, Any]) -> pd.DataFrame:
    cols = ["agent_id","period","call_type","metric","score_risk"]
    if signals is None or signals.empty:
        return pd.DataFrame(columns=cols)
    df = signals.copy()
    gap = pd.to_numeric(df.get("gap"), errors="coerce").abs().fillna(0.0)
    conf = pd.to_numeric(df.get("confidence"), errors="coerce").fillna(0.0)
    # risk = gap * (1 - confidence)
    df["score_risk"] = (gap * (1.0 - conf)).fillna(0.0)
    return df[["agent_id","period","call_type","metric","score_risk"]]
