from __future__ import annotations

from typing import Any, Dict, Tuple

import pandas as pd

from cde.utils.logging import get_logger

log = get_logger(__name__)


def normalize_inputs(raw, config: Dict[str, Any]) -> Dict[str, pd.DataFrame]:
    """
    Normalizes raw tables into canonical column names and a minimal engine input mart.

    Strategy:
    - apply table-specific renames from config (optional)
    - optionally build a merged 'engine_inputs' table if config declares join keys and sources

    This keeps PoC friction low while enforcing canonical naming.
    """
    renames_cfg = (config.get("normalization") or {}).get("renames", {})
    out: Dict[str, pd.DataFrame] = {}

    for name, df in raw.tables.items():
        df2 = df.copy()
        if name in renames_cfg:
            df2 = df2.rename(columns=renames_cfg[name])
        out[name] = df2

    # Optional: build engine_inputs by joining declared sources on entity keys
    join_cfg = (config.get("normalization") or {}).get("build_engine_inputs")
    if join_cfg:
        entity = config.get("entity_keys", {"agent_id": "agent_id", "period": "week_start"})
        agent_key = entity["agent_id"]
        period_key = entity["period"]

        sources = join_cfg.get("sources", [])
        if not sources:
            raise ValueError("normalization.build_engine_inputs.sources is empty.")

        base_name = sources[0]
        if base_name not in out:
            raise ValueError(f"Base source table missing: {base_name}")

        merged = out[base_name]
        for other in sources[1:]:
            if other not in out:
                raise ValueError(f"Join source table missing: {other}")
            merged = merged.merge(out[other], on=[agent_key, period_key], how="left", suffixes=("", f"__{other}"))

        out["engine_inputs"] = merged
        log.info("Built 'engine_inputs' by joining sources: %s", sources)

    return out
