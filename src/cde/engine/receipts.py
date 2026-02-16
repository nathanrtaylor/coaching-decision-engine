# src/cde/engine/receipts.py

from __future__ import annotations

import json
from typing import Any, Dict, Optional

import pandas as pd

from cde.explainability.evidence import build_competitors
from cde.explainability.templates import narrative_why_this, narrative_why_now, narrative_why_not


def build_receipts(
    recommendations: pd.DataFrame,
    candidates: pd.DataFrame,
    signals: Optional[pd.DataFrame],
    scores: Optional[pd.DataFrame],
    config: Dict[str, Any],
    excluded_signals: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """
    Build structured "decision receipts" for each recommendation.

    Receipts answer:
      - why this topic (drivers + weights + benchmark/gap)
      - why now (risk/trend/confidence)
      - why not others (top competitors)
      - why some signals did not qualify (excluded_signals with reason codes)
      - provenance (config version, data snapshot, engine version)

    Notes:
      - candidates are topic-level candidates (post-thresholding + post-scoring)
      - excluded_signals are signal-level exclusions from apply_signal_thresholds()
    """
    if recommendations.empty:
        return pd.DataFrame([])

    recs = recommendations.copy()

    # Build competitor set ("why not others")
    comps = build_competitors(recs, candidates, config)

    receipts = []
    for _, r in recs.iterrows():
        agent_id = r["agent_id"]
        period = r["period"]
        call_type = r.get("call_type")

        # Competitors for this agent-period-call_type
        comp_rows = comps[
            (comps["agent_id"] == agent_id)
            & (comps["period"] == period)
            & (comps["call_type"] == call_type)
        ]
        competitors = comp_rows.to_dict(orient="records") if not comp_rows.empty else []

        # Excluded signals for this agent-period-call_type (signal-level)
        excluded_for_agent = []
        if excluded_signals is not None and not excluded_signals.empty:
            ex = excluded_signals[
                (excluded_signals["agent_id"] == agent_id)
                & (excluded_signals["period"] == period)
                & (excluded_signals["call_type"] == call_type)
            ]
            excluded_for_agent = ex.to_dict(orient="records") if not ex.empty else []

        # Drivers: start with the single strongest driver embedded in recommendations
        driver = {
            "metric": r.get("metric"),
            "value": _float_or_none(r.get("value")),
            "benchmark": _float_or_none(r.get("benchmark")),
            "gap": _float_or_none(r.get("gap")),
            "level_score": _float_or_none(r.get("level_score"), default=0.0),
            "trend_score": _float_or_none(r.get("trend_score"), default=0.0),
            "risk_score": _float_or_none(r.get("risk_score"), default=0.0),
            "confidence_score": _float_or_none(r.get("confidence_score"), default=0.0),
            "metric_weight": _float_or_none(r.get("metric_weight"), default=0.0),
            "topic_weight": _float_or_none(r.get("topic_weight"), default=0.0),
        }

        # Provenance
        meta = config.get("meta") or {}
        receipt = {
            "agent_id": agent_id,
            "period": period,
            "call_type": call_type,
            "recommended_topic": r["topic"],
            "conversation_type": r.get("conversation_type"),
            "priority_score": _float_or_none(r.get("priority_score"), default=0.0),
            "drivers": [driver],
            "competing_topics": competitors,
            "excluded_signals": excluded_for_agent,
            "narrative": {
                "why_this": narrative_why_this(r),
                "why_now": narrative_why_now(r),
                "why_not_others": narrative_why_not(competitors),
            },
            "provenance": {
                "config_version": meta.get("version"),
                "data_snapshot": meta.get("data_snapshot"),
                "engine_version": meta.get("engine_version", "0.1.0"),
            },
        }
        receipts.append(receipt)

    return pd.DataFrame(receipts)


def receipts_to_jsonl(receipts: pd.DataFrame) -> str:
    """
    Serialize receipts to JSONL.
    Each row is a JSON object (one receipt per line).
    """
    lines = []
    for _, row in receipts.iterrows():
        obj = row.to_dict()

        # Ensure pandas/numpy types don't break JSON serialization
        obj = _json_safe(obj)

        lines.append(json.dumps(obj, ensure_ascii=False))
    return "\n".join(lines) + "\n"


def _float_or_none(x: Any, default: Optional[float] = None) -> Optional[float]:
    if x is None:
        return default
    try:
        if isinstance(x, float) and pd.isna(x):
            return default
        return float(x)
    except Exception:
        return default


def _json_safe(obj: Any) -> Any:
    """
    Convert nested structures containing pandas/numpy scalars to JSON-safe python types.
    """
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(v) for v in obj]
    # pandas NA checks
    try:
        if isinstance(obj, float) and pd.isna(obj):
            return None
    except Exception:
        pass
    # numpy / pandas scalar -> python scalar
    try:
        if hasattr(obj, "item"):
            return obj.item()
    except Exception:
        pass
    return obj
