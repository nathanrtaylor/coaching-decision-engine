# src/cde/scoring/assemble.py
from __future__ import annotations

from typing import Dict, Any
import pandas as pd
import numpy as np
import logging

from cde.scoring.score_level import score_level
from cde.scoring.score_trend import score_trend
from cde.scoring.score_risk import score_risk
from cde.scoring.score_confidence import score_confidence

log = logging.getLogger(__name__)

def _ensure_keys(df: pd.DataFrame) -> pd.DataFrame:
    # Normalize key column names expected downstream
    # Expect at least: agent_id, period, call_type, metric
    for k in ("agent_id", "period", "call_type", "metric"):
        if k not in df.columns:
            df[k] = None
    return df


def assemble_scores(signals: pd.DataFrame, config: Dict[str, Any]) -> pd.DataFrame:
    """
    Compose level/trend/risk/confidence scores into one scores dataframe.

    Returns a DataFrame with columns:
      agent_id, period, call_type, metric,
      score_level, score_trend, score_risk, score_confidence, score_total
    Always returns a DataFrame (empty if signals is empty).
    """
    log.info(
        "assemble_scores: received signals rows=%s",
        0 if signals is None else (signals.shape[0] if hasattr(signals, "shape") else "?")
    )

    if signals is None:
        log.warning("assemble_scores: received None signals; returning empty DataFrame")
        return pd.DataFrame(
            columns=[
                "agent_id", "period", "call_type", "metric",
                "score_level", "score_trend", "score_risk", "score_confidence", "score_total"
            ]
        )

    if signals.empty:
        log.info("assemble_scores: input signals is empty; returning empty scores DataFrame")
        return pd.DataFrame(
            columns=[
                "agent_id", "period", "call_type", "metric",
                "score_level", "score_trend", "score_risk", "score_confidence", "score_total"
            ]
        )

    # ensure canonical keys exist
    sig = _ensure_keys(signals.copy())

    # Each scoring function should return a DataFrame with at least:
    # agent_id, period, call_type, metric, <score_col>
    lvl = score_level(sig, config)
    trd = score_trend(sig, config)
    rsk = score_risk(sig, config)
    conf = score_confidence(sig, config)

    # Defensive: make sure returned objects are DataFrames
    for name, df in (("level", lvl), ("trend", trd), ("risk", rsk), ("confidence", conf)):
        if df is None:
            log.warning("assemble_scores: %s scorer returned None; replacing with empty DataFrame", name)
            if name == "level":
                lvl = pd.DataFrame(columns=["agent_id", "period", "call_type", "metric", "score_level"])
            if name == "trend":
                trd = pd.DataFrame(columns=["agent_id", "period", "call_type", "metric", "score_trend"])
            if name == "risk":
                rsk = pd.DataFrame(columns=["agent_id", "period", "call_type", "metric", "score_risk"])
            if name == "confidence":
                conf = pd.DataFrame(columns=["agent_id", "period", "call_type", "metric", "score_confidence"])

    # Merge on keys. Use outer merge to preserve rows, then fillna(0).
    base = sig[["agent_id", "period", "call_type", "metric"]].drop_duplicates()

    def _merge(df_left, df_right):
        if df_right is None or df_right.empty:
            return df_left
        return df_left.merge(
            df_right,
            on=["agent_id", "period", "call_type", "metric"],
            how="left"
        )

    merged = _merge(base, lvl)
    merged = _merge(merged, trd)
    merged = _merge(merged, rsk)
    merged = _merge(merged, conf)

    # Ensure score columns exist and numeric
    merged["score_level"] = pd.to_numeric(merged.get("score_level"), errors="coerce").fillna(0.0)
    merged["score_trend"] = pd.to_numeric(merged.get("score_trend"), errors="coerce").fillna(0.0)
    merged["score_risk"] = pd.to_numeric(merged.get("score_risk"), errors="coerce").fillna(0.0)
    merged["score_confidence"] = pd.to_numeric(merged.get("score_confidence"), errors="coerce").fillna(0.0)

    # Compute total score using priority_model weights (safe defaults)
    pm = config.get("priority_model") or {}
    w_level = float(pm.get("w_level", 0.5))
    w_trend = float(pm.get("w_trend", 0.2))
    w_risk = float(pm.get("w_risk", 0.3))
    # confidence can be neutral or included; use it to dampen risk if desired
    # we'll just include it as a simple modifier here (optional)
    # score_total = weighted sum of components (normalize weights)
    merged["score_total"] = (
        w_level * merged["score_level"] +
        w_trend * merged["score_trend"] +
        w_risk  * merged["score_risk"]
    )

    # Optional: apply confidence as multiplier to total (if you prefer)
    # merged["score_total"] = merged["score_total"] * (0.5 + 0.5 * merged["score_confidence"])

    # keep the expected columns only
    out_cols = [
        "agent_id", "period", "call_type", "metric",
        "score_level", "score_trend", "score_risk", "score_confidence", "score_total"
    ]
    for c in out_cols:
        if c not in merged.columns:
            merged[c] = 0.0 if c.startswith("score_") else None

    # keep the expected columns only
    out_cols = [
        "agent_id", "period", "call_type", "metric",
        "score_level", "score_trend", "score_risk", "score_confidence", "score_total"
    ]
    for c in out_cols:
        if c not in merged.columns:
            merged[c] = 0.0 if c.startswith("score_") else None

    # ------------------------------------------------------------------
    # Guardrail: enforce 1 row per scoring key (prevents downstream inflation)
    # If duplicates exist, keep the highest score_total deterministically.
    KEYS = ["agent_id", "period", "call_type", "metric"]
    dup_count = int(merged.duplicated(subset=KEYS, keep=False).sum())
    if dup_count:
        log.warning(
            "assemble_scores: found %s duplicate rows on keys=%s; de-duping by max(score_total).",
            dup_count, KEYS
        )
        merged = (
            merged.sort_values("score_total", ascending=False)
                  .drop_duplicates(subset=KEYS, keep="first")
                  .reset_index(drop=True)
        )
    # ------------------------------------------------------------------

    return merged[out_cols].copy()
