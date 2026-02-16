from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

import pandas as pd

from cde.engine.tie_breakers import deterministic_sort


@dataclass(frozen=True)
class Recommendation:
    agent_id: str
    period: str
    call_type: str
    topic: str
    conversation_type: str
    priority_score: float


def _conversation_type_for(topic: str, config: Dict[str, Any]) -> str:
    """
    Deterministic mapping from topic -> conversation type.
    Config example:
      conversation_types:
        default: "Performance Coaching"
        by_topic:
          "Reduce Transfer Rate": "Performance Correction"
    """
    ct = config.get("conversation_types") or {}
    by_topic = ct.get("by_topic") or {}
    return by_topic.get(topic, ct.get("default", "Performance Coaching"))


def recommend_for_population(topic_candidates: pd.DataFrame, config: Dict[str, Any]) -> pd.DataFrame:
    """
    Deterministic selection:
      - rank candidates per agent+period+call_type
      - select top 1
    """
    required = {"agent_id", "period", "call_type", "topic", "priority_score"}
    missing = required - set(topic_candidates.columns)
    if missing:
        raise ValueError(f"Candidates missing required columns: {sorted(missing)}")

    df = deterministic_sort(topic_candidates, config)
    top = df.groupby(["agent_id", "period", "call_type"], as_index=False).head(1).copy()

    top["conversation_type"] = top["topic"].apply(lambda t: _conversation_type_for(t, config))

    # Keep only essentials + evidence pointers
    cols = [
        "agent_id", "period", "call_type",
        "topic", "conversation_type",
        "priority_score",
        "metric", "value", "benchmark", "gap",
        "level_score", "trend_score", "risk_score", "confidence_score",
        "metric_weight", "topic_weight",
    ]
    keep = [c for c in cols if c in top.columns]
    return top[keep].reset_index(drop=True)
