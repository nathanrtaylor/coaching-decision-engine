from __future__ import annotations

from typing import Any, Dict, Optional

import pandas as pd


def apply_recent_coaching_dampening(candidates: pd.DataFrame, config: Dict[str, Any], history: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """
    Dampens topics recently coached to prevent whiplash.
    Deterministic: either suppress or apply multiplier.

    Expected history schema (optional):
      agent_id, topic, last_coached_period

    Config example:
      dampening:
        mode: "suppress"  # or "multiply"
        periods: 2
        multiplier: 0.5
    """
    df = candidates.copy()
    damp = config.get("dampening") or {}
    mode = damp.get("mode", "suppress")
    periods = int(damp.get("periods", 2))
    mult = float(damp.get("multiplier", 0.5))

    if history is None or history.empty:
        df["dampened"] = False
        return df

    # naive period difference: assumes period is comparable sortable value; for real use, convert to dates/ints
    hist = history.copy()
    hist = hist.rename(columns={"last_coached_period": "history_period"})

    joined = df.merge(hist[["agent_id", "topic", "history_period"]], on=["agent_id", "topic"], how="left")
    joined["dampened"] = False

    if "period" in joined.columns:
        # compute if history is within last N periods for the agent/topic
        # NOTE: for PoC we treat periods as sortable; replace with dates in utils.dates for production.
        recent = joined["history_period"].notna() & (joined["history_period"] >= joined["period"])
        # If periods are week starts, ">= period" isn't right—so we instead just dampen when history_period exists.
        # Prefer to upgrade to date diff when you wire real history.
        recent = joined["history_period"].notna()

        if mode == "suppress":
            joined = joined[~recent].copy()
        else:
            if "priority_score" in joined.columns:
                joined.loc[recent, "priority_score"] = joined.loc[recent, "priority_score"] * mult
            joined.loc[recent, "dampened"] = True

    return joined.drop(columns=["history_period"], errors="ignore")
