"""
tag_mapping.py

Deterministic Step 2b of Agent 2: flaw category -> question Type/Format.

Pure lookup table in app code (not an agent) so assignment is reproducible
and immune to model drift. Format defaults to 'Non-Sim'; a slot explicitly
tagged as a simulation (quota-planner 'Sim' format) keeps format 'Sim'.
Simulation questions are produced by the separate sim-generation track, not
retrieved from the non-sim banks.

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


def map_slot_tags(
    objective_type: str,
    style_constraint: str = '',
    requested_format: str | None = None,
) -> tuple[str, str]:
    """
    Returns (Type, Format) for a slot given its objective type and optional
    style constraint ('calculation' | 'proof' | '' | 'none').

    `requested_format` is the per-slot format emitted by the quota planner
    ('Sim' | 'Non-Sim'). Unrecognised or absent values degrade to the default
    'Non-Sim' format.
    """
    default, calc, proof = _TYPE_TABLE.get(objective_type, _FALLBACK)
    style = (style_constraint or '').strip().lower()

    if 'proof' in style:
        q_type = proof
    elif 'calcul' in style:
        q_type = calc
    else:
        q_type = default

    fmt = (requested_format or '').strip()
    if fmt not in ('Sim', 'Non-Sim'):
        fmt = DEFAULT_FORMAT

    return q_type, fmt


def enrich_slots(
    resolved_slots: list[dict],
    style_lookup: dict,
    format_lookup: dict | None = None,
) -> list[dict]:
    """
    Adds 'type' and 'format' to each resolved slot from step 2a.

    Args:
        resolved_slots: step 2a output, one dict per slot, each with
            slot_number, slot_objective, resolved_topic, resolved_subject,
            target_issue, keywords.
        style_lookup:  {slot_number: style_constraint} from the quota manifest.
        format_lookup: {slot_number: 'Sim'|'Non-Sim'} from the quota manifest
            per-slot format; falls back to DEFAULT_FORMAT when absent.

    Returns:
        A NEW list of slot dicts with type/format added. Input is not mutated.
    """
    fmt_lookup = format_lookup or {}
    enriched = []
    for slot in resolved_slots:
        slot_num = slot.get('slot_number')
        q_type, fmt = map_slot_tags(
            slot.get('slot_objective', ''),
            style_lookup.get(slot_num, ''),
            requested_format=fmt_lookup.get(slot_num),
        )
        enriched.append({**slot, 'type': q_type, 'format': fmt})
    return enriched
