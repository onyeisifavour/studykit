"""
sequencer.py

Deterministic sequencing steps for Agent 4 (Pedagogical Sequence Builder).

Agent 4 is a split pipeline: 4a (pacing arc) is the only AI judgment step;
steps 4b-4d are mechanical code:

  4b  Bucket selected items by objective_type -> pacing stage, sort within
      each stage by match_confidence (high -> low), then concatenate stages
      in the order chosen by the 4a pacing arc.
  4c  Pick the Gateway (most approachable item) as position 1, then do a
      context-switch pass that keeps same-topic (and same-sim-set) items
      consecutive inside each stage run.
  4d  Assign sequence_index / pacing_stage / position_rationale and assemble
      the sequenced quiz manifest that Agent 5 consumes.

This module never edits, rewrites, or drops question text. It only orders the
items it is given and documents why.
"""

from __future__ import annotations

from typing import Any

# objective_type -> pacing stage. Objective types are the Agent 2/3 labels;
# the arc stages are the Agent 4 labels. Items whose objective_type is unknown
# default to the core concept gap stage so they are never silently dropped.
STAGE_MAP = {
    "prerequisite_repair": "prerequisite_repair",
    "conceptual_gap": "core_concept_gap",
    "transfer_mechanism": "transfer_elevation",
    "synthesis_elevation": "transfer_elevation",
    "user_preference_finale": "user_preference_finale",
}

DEFAULT_STAGE_ORDER = [
    "warm_up",
    "prerequisite_repair",
    "core_concept_gap",
    "transfer_elevation",
    "user_preference_finale",
]

STAGE_LABELS = {
    "warm_up": "Warm-up / Confidence Anchor",
    "prerequisite_repair": "Prerequisite Repair",
    "core_concept_gap": "Core Concept Gap",
    "transfer_elevation": "Transfer / Elevation",
    "user_preference_finale": "User Preference Finale",
}

_CONFIDENCE_RANK = {"high": 0, "medium": 1, "low": 2}
_TYPE_RANK = {"MCQ": 3, "Hybrid": 2, "Theory": 1}
_OBJECTIVE_ANCHOR_RANK = {
    "conceptual_gap": 2,
    "prerequisite_repair": 1,
    "transfer_mechanism": 1,
    "synthesis_elevation": 1,
}


def _dedupe(items: list[dict]) -> list[dict]:
    """Drop exact duplicate dicts while preserving first-seen order."""
    seen: set[str] = set()
    out: list[dict] = []
    for it in items:
        key = json_key(it)
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def json_key(it: dict) -> str:
    import json

    return json.dumps(it, sort_keys=True)


def approachability_score(item: dict) -> float:
    """Higher = easier to warm up with. Prefers MCQ, short, non-sim, anchored."""
    q = item.get("selected_question", {})
    score = _TYPE_RANK.get(q.get("type", ""), 0) * 10.0
    if q.get("format", "Non-Sim") != "Sim":
        score += 5.0
    score += _OBJECTIVE_ANCHOR_RANK.get(item.get("objective_type", ""), 0) * 2.0
    text = q.get("text", "")
    if isinstance(text, str):
        score -= min(len(text), 400) / 40.0
    return score


def _normalise_stage_order(stage_sequence: Any) -> list[str]:
    if not isinstance(stage_sequence, list):
        return list(DEFAULT_STAGE_ORDER)
    valid = {s for s in DEFAULT_STAGE_ORDER}
    order = []
    for entry in stage_sequence:
        if isinstance(entry, dict):
            stage = entry.get("stage")
            if isinstance(stage, str) and stage in valid and stage not in order:
                order.append(stage)
    for stage in DEFAULT_STAGE_ORDER:
        if stage not in order:
            order.append(stage)
    return order


def _item_stage(item: dict) -> str:
    return STAGE_MAP.get(item.get("objective_type", ""), "core_concept_gap")


def _grouping_key(item: dict) -> tuple[str, ...]:
    """Consecutive-sim-set rule outranks topic grouping."""
    q = item.get("selected_question", {})
    sim_set = q.get("sim_set")
    if sim_set:
        return ("sim", q.get("sim_name", ""), str(sim_set))
    return (q.get("subject", ""), q.get("topic", ""))


def _stable_group_by_key(pairs: list[tuple[dict, str]]) -> list[tuple[dict, str]]:
    groups: dict[tuple[str, ...], list] = {}
    order: list[tuple[str, ...]] = []
    for pair in pairs:
        item, _ = pair
        key = _grouping_key(item)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(pair)
    return [p for k in order for p in groups[k]]


def _group_within_stages(pairs: list[tuple[dict, str]]) -> list[tuple[dict, str]]:
    result: list[tuple[dict, str]] = []
    i = 0
    while i < len(pairs):
        j = i
        while j < len(pairs) and pairs[j][1] == pairs[i][1]:
            j += 1
        result.extend(_stable_group_by_key(pairs[i:j]))
        i = j
    return result


def build_ordered_sequence(
    selected_items: list[dict],
    pacing_arc: dict | None = None,
) -> dict:
    """
    Convert selected items into the Agent 5 sequenced quiz manifest.

    Returns:
        {
            "sequence_metadata": {
                "total_questions": int,
                "pacing_strategy": str,
                "target_cognitive_flow": str,
            },
            "ordered_quiz_sequence": [
                {
                    "sequence_index": int,
                    "question": {...},
                    "objective_type": str,
                    "source": str,
                    "pacing_stage": str,
                    "position_rationale": str,
                },
                ...
            ],
        }
    """
    arc = pacing_arc if isinstance(pacing_arc, dict) else {}
    strategy = arc.get("pacing_strategy") or "Balanced Arc"
    cognitive_flow = arc.get("target_cognitive_flow") or ""
    stage_order = _normalise_stage_order(arc.get("stage_sequence"))

    items = _dedupe(selected_items)

    buckets: dict[str, list[dict]] = {}
    for item in items:
        buckets.setdefault(_item_stage(item), []).append(item)
    for stage, bucket in buckets.items():
        bucket.sort(key=lambda i: _CONFIDENCE_RANK.get(i.get("match_confidence", "medium"), 1))

    if not items:
        return {
            "sequence_metadata": {
                "total_questions": 0,
                "pacing_strategy": strategy,
                "target_cognitive_flow": cognitive_flow,
            },
            "ordered_quiz_sequence": [],
        }

    # Gateway: most approachable item becomes position 1 (the warm-up anchor).
    gateway_index = max(range(len(items)), key=lambda i: approachability_score(items[i]))
    gateway = items[gateway_index]
    gateway_stage = "warm_up"

    pairs: list[tuple[dict, str]] = []
    for stage in stage_order:
        for item in buckets.pop(stage, []):
            if item is not gateway:
                pairs.append((item, stage))
    for stage in DEFAULT_STAGE_ORDER:
        for item in buckets.pop(stage, []):
            if item is not gateway:
                pairs.append((item, stage))
    pairs.insert(0, (gateway, gateway_stage))

    pairs = _group_within_stages(pairs)

    sequence = []
    sim_sets: dict[str, int] = {}
    for i, (item, stage) in enumerate(pairs, start=1):
        q = item.get("selected_question", {})
        obj = item.get("objective_type", "")
        sim_set = q.get("sim_set")
        if stage == "warm_up":
            rationale = (
                "Most approachable item - anchors confidence and establishes a "
                "baseline before the diagnostic stages."
            )
        elif sim_set:
            n = sim_sets.setdefault(f"{q.get('sim_name', '')}|{sim_set}", 1)
            rationale = f"Kept consecutive with SimSet {sim_set} to preserve shared setup."
        else:
            rationale = (
                f"{obj} on {q.get('topic', '')} - placed in {STAGE_LABELS.get(stage, stage)} "
                f"following the {strategy} pacing strategy."
            )
        sequence.append(
            {
                "sequence_index": i,
                "question": q,
                "objective_type": obj,
                "source": item.get("source", "bank"),
                "pacing_stage": STAGE_LABELS.get(stage, stage),
                "position_rationale": rationale,
            }
        )

    return {
        "sequence_metadata": {
            "total_questions": len(sequence),
            "pacing_strategy": strategy,
            "target_cognitive_flow": cognitive_flow,
        },
        "ordered_quiz_sequence": sequence,
    }
