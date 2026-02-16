from __future__ import annotations

from typing import Any, Dict

import pandas as pd

from cde.scoring.score_level import score_level
from cde.scoring.score_trend import score_trend
from cde.scoring.score_confidence import score_confidence
from cde.scoring.score_risk import score_risk


def assemble_scores(signals: pd.DataFrame, config: Dict[str, Any]) -> pd.DataFrame:
  # Safety: if thresholding already ran upstream and marked an eligibility flag, filter here.
  if "is_eligible" in signals.columns:
    signals = signals[signals["is_eligible"] == True].copy()

    """
    Produces a long-form score table with multiple axes:
      level_score, trend_score, risk_score, confidence_score
    """
    lvl = score_level(signals, config)
    tr = score_trend(signals, config)
    conf = score_confidence(signals, config)
    risk = score_risk(signals, lvl, tr, config)

    out = risk.merge(conf, on=["agent_id", "period", "call_type", "metric"], how="left")
    return out
