# src/cde/scoring/score_level.py
from typing import Dict, Any
import pandas as pd
import numpy as np

def score_level(signals: pd.DataFrame, config: Dict[str, Any]) -> pd.DataFrame:
    cols = ["agent_id","period","call_type","metric","score_level"]
    if signals is None or signals.empty:
        return pd.DataFrame(columns=cols)
    df = signals.copy()
    # level = absolute gap (or value vs benchmark). Fallback to 0 if missing.
    df["score_level"] = (pd.to_numeric(df.get("gap"), errors="coerce").abs()).fillna(0.0)
    return df[["agent_id","period","call_type","metric","score_level"]]
