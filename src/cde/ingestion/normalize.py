from __future__ import annotations

from typing import Any, Dict

import numpy as np
import pandas as pd

from cde.utils.logging import get_logger

log = get_logger(__name__)


def normalize_inputs(raw, config: Dict[str, Any]) -> Dict[str, pd.DataFrame]:
    """
    Normalizes raw tables into canonical column names and a minimal engine input mart.

    Strategy:
    - apply table-specific renames from config (optional)
    - apply minimal canonicalization for known core tables (e.g., agent_metrics)
    - optionally build a merged 'engine_inputs' table if config declares join keys and sources

    This keeps PoC friction low while enforcing canonical naming and data types where it matters.
    """
    renames_cfg = (config.get("normalization") or {}).get("renames", {})
    out: Dict[str, pd.DataFrame] = {}

    for name, df in raw.tables.items():
        df2 = df.copy()

        # 1) Config-driven renames first
        if name in renames_cfg:
            df2 = df2.rename(columns=renames_cfg[name])

        # 2) Minimal canonicalization for core tables
        if name == "agent_metrics":
            # Ensure canonical period exists (support raw week_ending)
            if "period" not in df2.columns and "week_ending" in df2.columns:
                df2 = df2.rename(columns={"week_ending": "period"})

            # Coerce period to datetime early (prevents downstream merge dtype mismatches)
            if "period" in df2.columns:
                df2["period"] = pd.to_datetime(df2["period"], errors="coerce")

            # Coerce numeric inputs
            if "numerator" in df2.columns:
                df2["numerator"] = pd.to_numeric(df2["numerator"], errors="coerce")
            if "denominator" in df2.columns:
                df2["denominator"] = pd.to_numeric(df2["denominator"], errors="coerce")

            # Ensure value exists and compute deterministically when possible
            if "value" not in df2.columns:
                df2["value"] = np.nan

            if "numerator" in df2.columns and "denominator" in df2.columns:
                mask = (
                    df2["value"].isna()
                    & df2["numerator"].notna()
                    & df2["denominator"].notna()
                    & (df2["denominator"] != 0)
                )
                df2.loc[mask, "value"] = df2.loc[mask, "numerator"] / df2.loc[mask, "denominator"]

            # Standardize metric strings (helps benchmark/topic joins)
            if "metric" in df2.columns:
                df2["metric"] = df2["metric"].astype(str).str.strip()

        out[name] = df2

    # Optional: build engine_inputs by joining declared sources on entity keys
    join_cfg = (config.get("normalization") or {}).get("build_engine_inputs")
    if join_cfg:
        # Default entity keys should be canonical. If not specified, assume "period".
        entity = config.get("entity_keys", {"agent_id": "agent_id", "period": "period"})
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
            merged = merged.merge(
                out[other],
                on=[agent_key, period_key],
                how="left",
                suffixes=("", f"__{other}"),
            )

        out["engine_inputs"] = merged
        log.info("Built 'engine_inputs' by joining sources: %s", sources)

    return out