"""
tag_mapping.py

Deterministic Step 2b of Agent 2: flaw category -> question Type/Format.

Pure lookup table in app code (not an agent) so assignment is reproducible
and immune to model drift. Format is always 'Non-Sim' for now — simulation
questions are produced by the separate Sim pipeline (S1-S3), not retrieved
from the non-sim banks.

Table (from AGENT2_WORKFLOW_BLUEPRINT.md Step 2):
    objective_type        default   style=calculation   style=proof
    prerequisite_repair   MCQ       Hybrid              Theory
    conceptual_gap        Hybrid    Hybrid              Theory
    transfer_mechanism    Theory    Hybrid              Theory
    synthesis_elevation   Theory    Theory              Theory
"""

from __future__ import annotations

DEFAULT_FORMAT = 'Non-Sim'

# objective_type -> (default_type, style=calculation, style=proof)
_TYPE_TABLE = {
    'prerequisite_repair': ('MCQ',    'Hybrid', 'Theory'),
    'conceptual_gap':      ('Hybrid', 'Hybrid', 'Theory'),
    'transfer_mechanism':  ('Theory', 'Hybrid', 'Theory'),
    'synthesis_elevation': ('Theory', 'Theory', 'Theory'),
}

# If an objective_type isn't recognised, degrade to the MCQ baseline.
_FALLBACK = ('MCQ', 'Hybrid', 'Theory')


def map_slot_tags(objective_type: str, style_constraint: str = '') -> tuple[str, str]:
    """
    Returns (Type, Format) for a slot given its objective type and optional
    style constraint ('calculation' | 'proof' | '' | 'none').
    """
    default, calc, proof = _TYPE_TABLE.get(objective_type, _FALLBACK)
    style = (style_constraint or '').strip().lower()

    if 'proof' in style:
        q_type = proof
    elif 'calcul' in style:
        q_type = calc
    else:
        q_type = default

    return q_type, DEFAULT_FORMAT


def enrich_slots(resolved_slots: list[dict], style_lookup: dict) -> list[dict]:
    """
    Adds 'type' and 'format' to each resolved slot from step 2a.

    Args:
        resolved_slots: step 2a output, one dict per slot, each with
            slot_number, slot_objective, resolved_topic, resolved_subject,
            target_issue, keywords.
        style_lookup: {slot_number: style_constraint} from the quota manifest.

    Returns:
        A NEW list of slot dicts with type/format added. Input is not mutated.
    """
    enriched = []
    for slot in resolved_slots:
        enriched.append({
            **slot,
            'type':    map_slot_tags(
                slot.get('slot_objective', ''),
                style_lookup.get(slot.get('slot_number'), ''),
            )[0],
            'format':  DEFAULT_FORMAT,
        })
    return enriched
