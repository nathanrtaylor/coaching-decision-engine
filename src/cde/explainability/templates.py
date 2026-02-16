from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd


def narrative_why_this(rec_row: pd.Series) -> str:
    metric = rec_row.get("metric")
    gap = rec_row.get("gap")
    lvl = rec_row.get("level_score")
    return f"Selected because '{metric}' is the strongest driver for the chosen topic, with level_score={_fmt(lvl)} and gap={_fmt(gap)}."

def narrative_why_now(rec_row: pd.Series) -> str:
    trend = rec_row.get("trend_score")
    risk = rec_row.get("risk_score")
    conf = rec_row.get("confidence_score")
    return f"Recommended now due to urgency signals: trend_score={_fmt(trend)}, risk_score={_fmt(risk)}, confidence={_fmt(conf)}."

def narrative_why_not(competitors: List[Dict[str, Any]]) -> str:
    if not competitors:
        return "No other eligible topics exceeded thresholds under current rules."
    top = competitors[0]
    return f"Next-best alternative was '{top.get('topic')}', but it was not selected because: {top.get('reason_not_selected')}."

def _fmt(x: Any) -> str:
    try:
        if x is None or (isinstance(x, float) and pd.isna(x)):
            return "NA"
        return f"{float(x):.3f}"
    except Exception:
        return str(x)
