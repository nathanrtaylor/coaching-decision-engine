# src/cde/prioritization/apply.py

from __future__ import annotations

from typing import Any, Dict

import pandas as pd

from cde.prioritization.weights import get_metric_weight, get_topic_weight
from cde.prioritization.eligibility import apply_eligibility


def _load_topic_map(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Expects config["topic_map"] to be the loaded YAML from mappings/topic_map.yaml:

      topic_map:
        metric_to_topic: {...}
        topic_to_conversation_type: {...}
        allowed_topics_by_call_type: {...}

    Returns the inner dict under the 'topic_map' root (or {}).
    """
    tm = config.get("topic_map") or {}
    # handle either shape:
    # 1) {"topic_map": {...}} (recommended)
    # 2) {...} (if you load inner dict directly)
    return tm.get("topic_map", tm) if isinstance(tm, dict) else {}


def build_topic_candidates(signals: pd.DataFrame, scores: pd.DataFrame, config: Dict[str, Any]) -> pd.DataFrame:
    """
    Produces candidate topics with explicit scoring components and a deterministic
    'priority_score' used ONLY for selection / ranking.

    Updates vs prior version:
      - metric -> topic mapping is now loaded from mappings/topic_map.yaml
      - unmapped metrics are dropped by default (prevents topic explosion)
      - optional semantic constraints allowed_topics_by_call_type can be enforced here
        (eligibility layer can still enforce hard rules too)
    """
    tm = _load_topic_map(config)
    metric_to_topic = tm.get("metric_to_topic") or {}
    allowed_topics_by_ct = tm.get("allowed_topics_by_call_type") or {}

    allow_unmapped = bool((config.get("topic_map_options") or {}).get("allow_unmapped_metrics", False))

    # Join scores with key signal evidence
    df = scores.merge(
        signals[["agent_id", "period", "call_type", "metric", "value", "benchmark", "gap", "direction"]],
        on=["agent_id", "period", "call_type", "metric"],
        how="left",
    )

    # Backward/forward compatible score column naming
    rename_map = {
        "score_level": "level_score",
        "score_trend": "trend_score",
        "score_risk": "risk_score",
        "score_confidence": "confidence_score",
        "score_total": "total_score",   
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})

    # Map canonical metric -> topic (drop if unmapped unless explicitly allowed)
    df["topic"] = df["metric"].map(metric_to_topic)
    if allow_unmapped:
        df["topic"] = df["topic"].fillna(df["metric"])
    else:
        df = df[df["topic"].notna()].copy()

    # Optional semantic constraints from topic_map.yaml
    # (This is not a substitute for eligibility rules; it’s a helpful guardrail.)
    if allowed_topics_by_ct and "call_type" in df.columns:
        allowed_sets = {ct: set(topics) for ct, topics in allowed_topics_by_ct.items()}
        keep_mask = []
        for ct, topic in zip(df["call_type"].tolist(), df["topic"].tolist()):
            if ct in allowed_sets:
                keep_mask.append(topic in allowed_sets[ct])
            else:
                keep_mask.append(True)
        df = df[pd.Series(keep_mask, index=df.index)].copy()

    # Compute deterministic priority_score (transparent linear composition)
    pri_model = config.get("priority_model") or {}
    w_level = float(pri_model.get("w_level", 0.5))
    w_trend = float(pri_model.get("w_trend", 0.2))
    w_risk = float(pri_model.get("w_risk", 0.3))
    w_conf = float(pri_model.get("w_confidence", 0.0))  # usually gate, not driver

    df["metric_weight"] = [
        get_metric_weight(m, ct, config) for m, ct in zip(df["metric"].tolist(), df["call_type"].tolist())
    ]
    df["topic_weight"] = [
        get_topic_weight(t, ct, config) for t, ct in zip(df["topic"].tolist(), df["call_type"].tolist())
    ]

    base = (
        w_level * df["level_score"].fillna(0.0)
        + w_trend * df["trend_score"].fillna(0.0)
        + w_risk * df["risk_score"].fillna(0.0)
        + w_conf * df["confidence_score"].fillna(0.0)
    )

    df["priority_score"] = (base * df["metric_weight"] * df["topic_weight"]).astype(float)

    # Aggregate to topic-level candidates per agent/period/call_type
    # Keep the "top metric driver" as evidence
    df = df.sort_values(
        ["agent_id", "period", "call_type", "topic", "priority_score"],
        ascending=[True, True, True, True, False],
    )
    top_driver = df.groupby(["agent_id", "period", "call_type", "topic"]).head(1).copy()

    agg = df.groupby(["agent_id", "period", "call_type", "topic"], as_index=False).agg(
        priority_score=("priority_score", "max"),
        level_score=("level_score", "max"),
        trend_score=("trend_score", "max"),
        risk_score=("risk_score", "max"),
        confidence_score=("confidence_score", "min"),  # conservative
    )

    out = agg.merge(
        top_driver[
            [
                "agent_id",
                "period",
                "call_type",
                "topic",
                "metric",
                "value",
                "benchmark",
                "gap",
                "metric_weight",
                "topic_weight",
            ]
        ],
        on=["agent_id", "period", "call_type", "topic"],
        how="left",
        suffixes=("", "_driver"),
    )

    out = apply_eligibility(out, config)
    return out
