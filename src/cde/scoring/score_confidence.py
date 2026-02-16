# src/cde/scoring/score_confidence.py
from typing import Dict, Any
import pandas as pd

def score_confidence(signals: pd.DataFrame, config: Dict[str, Any]) -> pd.DataFrame:
    cols = ["agent_id","period","call_type","metric","score_confidence"]
    if signals is None or signals.empty:
        return pd.DataFrame(columns=cols)
    df = signals.copy()
    df["score_confidence"] = pd.to_numeric(df.get("confidence"), errors="coerce").fillna(0.0)
    return df[["agent_id","period","call_type","metric","score_confidence"]]
