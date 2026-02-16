# Coaching Decision Engine

Deterministic, explainable system for recommending the most appropriate
coaching topic and conversation type for a given coaching session.

This engine translates operational performance data into governed
coaching recommendations that are:

-   Business-aligned\
-   Deterministic\
-   Versioned\
-   Auditable\
-   Explainable

It is designed to absorb frequent priority changes without losing rigor
or credibility.

------------------------------------------------------------------------

# Architecture Overview

The system follows a layered, modular architecture:

    Raw Data (CSV snapshots)
        ↓
    Signal Construction
        ↓
    Signal Gating (Thresholds)
        ↓
    Multi-Axis Scoring
        ↓
    Prioritization (Versioned Weights)
        ↓
    Deterministic Topic Selection
        ↓
    Decision Receipts

## Core Design Principles

-   **Business outcomes beat behavioral purity**
-   **Determinism is a feature**
-   **Explainability is mandatory**
-   **Flexibility must be governed**
-   **Configuration lives inside the system**
-   **Learning is constrained and human-controlled**

------------------------------------------------------------------------

# Repository Structure

    configs/
      active.yaml                # Current configuration pointer
      mappings/
        source_catalog.yaml
        metric_catalog.yaml
        topic_map.yaml
        benchmarks.yaml
      thresholds/
        signal_thresholds.yaml
      priorities/
        vYYYY_MM_DD_*.yaml

    data/
      raw/
        weekly/<snapshot_id>/    # Immutable source drops
      samples/

    src/cde/
      ingestion/
      signals/
      scoring/
      prioritization/
      engine/
      simulation/
      governance/

    outputs/
      runs/<timestamp>/

------------------------------------------------------------------------

# Configuration Layers

Each configuration file has a single responsibility.

  -------------------------------------------------------------------------------
  Layer                 File                       Purpose
  --------------------- -------------------------- ------------------------------
  Source ingestion      `source_catalog.yaml`      Defines dataset schemas +
                                                   computation rules

  Metric registry       `metric_catalog.yaml`      Canonical metric definitions +
                                                   governance

  Topic semantics       `topic_map.yaml`           Metric → coaching topic
                                                   mapping

  Benchmarks            `benchmarks.yaml`          Target/reference values

  Signal gating         `signal_thresholds.yaml`   Eligibility rules

  Business emphasis     `priorities/*.yaml`        Versioned weight
                                                   configurations

  Active pointer        `active.yaml`              Selects current config set
  -------------------------------------------------------------------------------

Only `priorities/` and `active.yaml` should change frequently.

------------------------------------------------------------------------

# Data Model

All sources are tall-skinny tables at this grain:

    agent_id × week_start × call_type × metric_key

Required columns (per source schema):

-   `agent_id`
-   `week_start`
-   `call_type` (can be logically disabled)
-   `metric_key`
-   `numerator`
-   `denominator` (nullable for score metrics)
-   `calculation`
-   `value` (optional)

Data is exported into:

    data/raw/weekly/<snapshot_id>/

Snapshots are immutable.

------------------------------------------------------------------------

# Running the System

## 1. Generate Raw Snapshot

Create a dated folder:

    data/raw/weekly/2026-02-16/

Export one CSV per source:

    agent_metrics.csv
    behavior_scores.csv
    expert_assist.csv
    smart_offer.csv

Optional but recommended:

    README.md
    checksums.sha256

------------------------------------------------------------------------

## 2. Run Extract (Optional Automation)

If using SQL extract automation:

    cde-run-extract \
      --manifest queries/manifest.yaml \
      --snapshot-id 2026-02-16 \
      --out-dir data/raw/weekly/2026-02-16 \
      --sqlalchemy-url "<connection-string>"

------------------------------------------------------------------------

## 3. Run Pipeline

    cde-run-pipeline \
      --raw-dir data/raw/weekly/2026-02-16 \
      --out-dir outputs/runs/2026-02-16_1530 \
      --configs-dir configs

Outputs:

    recommendations.csv
    decision_receipts.jsonl
    excluded_signals.csv
    manifest.json
    config_snapshot/

------------------------------------------------------------------------

# Decision Receipts

Every recommendation includes:

-   Why this topic
-   Why now
-   Why not others
-   Excluded signals (with reason codes)
-   Config version
-   Data snapshot ID
-   Engine version

Receipts are stored as JSONL for auditability and downstream ingestion.

------------------------------------------------------------------------

# Call Type Handling

Call types can be logically disabled without removing them from the data
model.

In `active.yaml`:

``` yaml
call_type_mode: disabled
default_call_type: "all_calls"
```

This collapses segmentation while preserving future extensibility.

------------------------------------------------------------------------

# Governance Model

-   Coaching Technology owns engine behavior.
-   Ops Leadership owns priorities.
-   Analytics supports validation and controlled discovery.

Configuration changes are versioned and auditable.

Ungoverned overrides are considered system failure.

------------------------------------------------------------------------

# Current Status

This repository supports:

-   Multi-source tall-skinny ingestion
-   Deterministic signal computation
-   Configurable signal gating
-   Versioned priority weighting
-   Deterministic topic selection
-   Explainable decision receipts
-   Snapshot reproducibility

------------------------------------------------------------------------

# Next Steps (Recommended)

-   Add scenario simulation for priority sensitivity
-   Add unit tests enforcing deterministic behavior
-   Add data validation CLI for snapshot health checks
-   Integrate coaching history for dampening logic

------------------------------------------------------------------------

# Guiding Principle

The system should not slow leaders down.\
It should make fast decisions work on purpose.
