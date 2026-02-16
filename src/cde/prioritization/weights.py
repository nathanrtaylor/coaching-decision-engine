from __future__ import annotations

from typing import Any, Dict, Optional


def get_metric_weight(metric: str, call_type: Optional[str], config: Dict[str, Any]) -> float:
    """
    Weight lookup order:
      priorities.weights.by_call_type[call_type][metric] -> priorities.weights.global[metric] -> default 0
    """
    pri = config.get("priorities") or {}
    weights = pri.get("weights") or {}
    by_ct = weights.get("by_call_type") or {}
    global_w = weights.get("global") or {}
    default_w = float(weights.get("default", 0.0))

    if call_type and call_type in by_ct and metric in by_ct[call_type]:
        return float(by_ct[call_type][metric])
    if metric in global_w:
        return float(global_w[metric])
    return default_w


def get_topic_weight(topic: str, call_type: Optional[str], config: Dict[str, Any]) -> float:
    """
    Same pattern as metric weights, but for topics (post-mapping layer).
    """
    pri = config.get("priorities") or {}
    weights = pri.get("topic_weights") or {}
    by_ct = weights.get("by_call_type") or {}
    global_w = weights.get("global") or {}
    default_w = float(weights.get("default", 1.0))

    if call_type and call_type in by_ct and topic in by_ct[call_type]:
        return float(by_ct[call_type][topic])
    if topic in global_w:
        return float(global_w[topic])
    return default_w
