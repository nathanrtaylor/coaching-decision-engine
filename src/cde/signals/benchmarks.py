from __future__ import annotations

from typing import Any, Dict, Optional

import pandas as pd


def get_benchmark_value(metric: str, call_type: Optional[str], config: Dict[str, Any]) -> Optional[float]:
    """
    Returns a benchmark for a metric, optionally by call_type.

    Config expectation (example):
      benchmarks:
        transfer_rate:
          default: 0.12
          by_call_type:
            claims: 0.10
            tech_support: 0.14
    """
    b = (config.get("benchmarks") or {}).get(metric)
    if not b:
        return None

    if call_type and isinstance(b, dict):
        by_ct = b.get("by_call_type") or {}
        if call_type in by_ct:
            return float(by_ct[call_type])

        if "default" in b:
            return float(b["default"])

    # allow direct scalar benchmark
    if isinstance(b, (int, float)):
        return float(b)

    return None


def benchmark_gap(value: float, benchmark: Optional[float]) -> Optional[float]:
    if benchmark is None:
        return None
    return float(value - benchmark)
