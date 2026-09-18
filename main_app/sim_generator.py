"""
sim_generator.py

Mechanical helpers for the simulation-question track of the quiz pipeline.

Slots the quota planner tagged `format: 'Sim'` are NOT retrieved from the
non-sim banks. Instead, the sim-question-generator agent authors a question
from the selected topic's simulation README. This module covers everything
that is deterministic code:

  - splitting a quota manifest by per-slot format (Sim vs Non-Sim)
  - resolving a slot's topic to a simulation README
  - parsing / validating the agent's JSON response into a selected item
  - assembling the sim-track selection manifest
  - merging the independent Non-Sim and Sim selection manifests

Slots whose resolved topic has no simulation README degrade to a missing item
with reason 'NO_SIM_AVAILABLE' (same reduced-quiz semantics as a missing bank
item downstream).

No agent or network calls are made from this module; agent_runner owns them.
"""

from __future__ import annotations

from typing import Any, Optional

VALID_QUESTION_TYPES = {'MCQ', 'Hybrid', 'Theory'}
VALID_CONFIDENCE = {'high', 'medium', 'low'}

MISSING_REASON_NO_SIM = 'NO_SIM_AVAILABLE'


# ── Slot splitting ────────────────────────────────────────────────────────────

def resolve_slot_formats(quota_manifest: dict, prefs: Optional[dict] = None) -> None:
    """
    Fills in a per-slot 'format' for any slot the quota planner left unset.

    The quota planner tags slots 'Sim'/'Non-Sim' at its discretion, but it may
    omit the field entirely. When it does, this derives the format
    deterministically from the user's section preferences so that, e.g. a
    simulation-only quiz does not silently fall back to the non-sim banks.

    Section assignment is derived from the slot's question Type (computed via
    the mechanical tag table): Theory → Section B, MCQ/Hybrid → Section A.
    Within that section, if exactly one of sim/non-sim is requested the slot is
    forced accordingly; otherwise the existing/default format is kept.
    """
    prefs = prefs or {}
    a_sim, a_nonsim = bool(prefs.get('section_a_sim')), bool(prefs.get('section_a_nonsim'))
    b_sim, b_nonsim = bool(prefs.get('section_b_sim')), bool(prefs.get('section_b_nonsim'))

    def _section_format(section: str, current: Optional[str]) -> Optional[str]:
        if section == 'A':
            sim, non = a_sim, a_nonsim
        else:
            sim, non = b_sim, b_nonsim
        if sim and not non:
            return 'Sim'
        if non and not sim:
            return 'Non-Sim'
        return current if current in ('Sim', 'Non-Sim') else None

    for slot in quota_manifest.get('slot_allocations', []):
        if not isinstance(slot, dict):
            continue
        current = slot.get('format')
        if current in ('Sim', 'Non-Sim'):
            continue
        from .tag_mapping import map_slot_tags
        q_type, _default_fmt = map_slot_tags(
            slot.get('objective_type', ''),
            slot.get('style_constraint', ''),
            requested_format=current if isinstance(current, str) else None,
        )
        section = 'B' if q_type == 'Theory' else 'A'
        resolved = _section_format(section, current if isinstance(current, str) else None)
        if resolved:
            slot['format'] = resolved


def split_slots_by_format(quota_manifest: dict) -> tuple[list[dict], list[dict]]:
    """
    Splits a quota manifest's slot_allocations into (non_sim_slots, sim_slots)
    based on each slot's `format` field (default 'Non-Sim').
    """
    slots = quota_manifest.get('slot_allocations', [])
    non_sim: list[dict] = []
    sim: list[dict] = []
    for slot in slots:
        if not isinstance(slot, dict):
            continue
        if str(slot.get('format', 'Non-Sim')) == 'Sim':
            sim.append(slot)
        else:
            non_sim.append(slot)
    return non_sim, sim


def filter_manifest_by_slots(quota_manifest: dict, slots: list[dict]) -> dict:
    """Returns a copy of the quota manifest restricted to the given slots."""
    included = {s.get('slot_number') for s in slots if isinstance(s, dict)}
    return {
        **quota_manifest,
        'slot_allocations': [
            s for s in quota_manifest.get('slot_allocations', [])
            if isinstance(s, dict) and s.get('slot_number') in included
        ],
    }


def build_sim_only_query_spec(enriched_slots: list[dict]) -> dict:
    """
    Builds a file-query spec manifest mechanically for a fully-sim quota.

    When every slot is format='Sim' the pipeline must not engage the question
    banks at all — there is no candidate selection or file retrieval — so the
    fallback-builder agent call (step 2c) is skipped. This manifest keeps the
    validated shape (three search tiers per slot) purely so downstream code can
    read each slot's resolved topic when locating the simulation README; the
    tiers are never used for bank matching.
    """
    specs = []
    for slot in enriched_slots:
        tier = {
            'subject': slot.get('resolved_subject', ''),
            'topic': slot.get('resolved_topic', ''),
            'type': slot.get('type', 'MCQ'),
            'format': slot.get('format', 'Sim'),
        }
        specs.append({
            'slot_number': slot.get('slot_number'),
            'slot_objective': slot.get('slot_objective', ''),
            'search_tiers': {
                'tier_1_exact': dict(tier),
                'tier_2_topic_fallback': dict(tier),
                'tier_3_type_relaxation': dict(tier),
            },
        })
    return {'file_query_specs': specs}


# ── README resolution ─────────────────────────────────────────────────────────

def resolve_readme(topic_files: list[dict], resolved_topic: str) -> Optional[dict]:
    """
    Finds the first simulation README for a resolved topic name.

    resolved_topic is the bank-topic name resolved in step 2a (carried by the
    2c tier_1_exact.topic). The resolver returns sub-topic names (e.g. 'Newton's
    Law of Universal Gravitation'), which are broader than the topic folder they
    belong to, so exact folder-name matching alone would miss every README.

    Matching order:
        1. Exact, case-insensitive topic_name match.
        2. Containment: the resolved name or the folder name contains the other
           (a sub-topic name always nests inside its folder's coverage).
        3. Generic fallback: only when the selected topics expose exactly one
           topic with a README — the simulator READMEs are per-topic, so a
           single-topic quiz has exactly one candidate.

    Returns None when the topic is unknown or has no README (→ NO_SIM_AVAILABLE).
    """
    wanted = (resolved_topic or '').strip().lower()
    if not wanted:
        return None
    with_readmes = []
    for tf in topic_files:
        name = (tf.get('topic_name') or '').strip().lower()
        readmes = tf.get('sim_readmes', [])
        usable = [r for r in readmes
                  if isinstance(r, dict) and r.get('content')
                  and r['content'].strip()]
        if usable and name == wanted:
            return usable[0]
        if usable:
            with_readmes.append((name, usable))
    # Containment match on the folder covering the resolved sub-topic.
    for name, usable in with_readmes:
        if name and (wanted in name or name in wanted):
            return usable[0]
    # Generic fallback: exactly one topic carries simulator READMEs.
    if len(with_readmes) == 1:
        return with_readmes[0][1][0]
    return None


# ── Agent response parsing ────────────────────────────────────────────────────

def parse_sim_question_response(text: str) -> tuple[Optional[dict], Optional[str]]:
    """
    Parses and validates the sim-question-generator agent's JSON response.

    Expected shape (one slot per call):

        {
          "slot_number": int,
          "question": {
            "text": str,
            "type": "MCQ" | "Hybrid" | "Theory",
            "options": [str, ...],            # empty for non-MCQ
            "correct_answer": str,
            "subject": str,
            "topic": str,
            "sim_name": str,
            "sim_instruction": str
          },
          "objective_type": str,
          "match_confidence": "high"|"medium"|"low",   # optional
          "selection_rationale": str                   # optional
        }

    Returns (normalised_item, None) on success or (None, error_detail). The
    item's selected_question.format is forced to 'Sim'.
    """
    import json
    import re

    text = (text or '').strip()

    def _raw_parse(raw: str):
        raw = raw.strip()
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    parsed = None
    # Prefer content inside ```json ... ``` fences if present.
    m = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if m:
        parsed = _raw_parse(m.group(1))
    # Fall back to full-text parse.
    if parsed is None:
        parsed = _raw_parse(text)
    # Last resort: brace extraction.
    if parsed is None:
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end > start:
            parsed = _raw_parse(text[start:end + 1])

    if parsed is None:
        return None, 'Response is not valid JSON.'

    if not isinstance(parsed, dict):
        return None, 'Expected a JSON object with a "question".'

    num = parsed.get('slot_number')
    if not isinstance(num, int):
        return None, 'slot_number must be an integer.'

    q = parsed.get('question')
    if not isinstance(q, dict):
        return None, 'Missing "question" object.'

    errs: list[str] = []
    q_text = q.get('text')
    if not isinstance(q_text, str) or not q_text.strip():
        errs.append('question.text must be a non-empty string')

    q_type = q.get('type')
    if not isinstance(q_type, str) or q_type not in VALID_QUESTION_TYPES:
        errs.append(f'question.type must be one of {sorted(VALID_QUESTION_TYPES)}')

    answer = q.get('correct_answer')
    if not isinstance(answer, str) or not answer.strip():
        errs.append('question.correct_answer must be a non-empty string')

    opts = q.get('options')
    if opts is not None and (
        not isinstance(opts, list) or not all(isinstance(o, str) for o in opts)
    ):
        errs.append('question.options must be a list of strings')

    for key in ('subject', 'topic', 'sim_name', 'sim_instruction'):
        value = q.get(key)
        if not isinstance(value, str) or not value.strip():
            errs.append(f'question.{key} must be a non-empty string')

    obj = parsed.get('objective_type')
    if not isinstance(obj, str) or not obj.strip():
        errs.append('objective_type must be a non-empty string')

    conf = parsed.get('match_confidence', 'medium')
    if conf not in VALID_CONFIDENCE:
        errs.append(f'match_confidence must be one of {sorted(VALID_CONFIDENCE)}')

    if errs:
        return None, '; '.join(errs)

    return {
        'slot_number': num,
        'selected_question': {
            'text': q_text,
            'type': q_type,
            'subject': q.get('subject'),
            'topic': q.get('topic'),
            'format': 'Sim',
            'options': opts if isinstance(opts, list) else [],
            'correct_answer': answer,
            'sim_name': q.get('sim_name'),
            'sim_instruction': q.get('sim_instruction'),
        },
        'objective_type': obj,
        'source': 'sim_generated',
        'match_confidence': conf,
        'selection_rationale': (
            parsed.get('selection_rationale')
            or parsed.get('rationale')
            or 'Simulation question generated from the topic README.'
        ),
    }, None


# ── Manifest assembly ─────────────────────────────────────────────────────────

def build_missing_item(slot_number: int, reason: str) -> dict:
    return {'slot_number': slot_number, 'reason': reason}


def assemble_sim_manifest(
    slots: list[dict],
    items: list[dict],
    missing: list[dict],
) -> dict:
    """Builds the sim-track selection manifest (selected + missing)."""
    return {
        'selection_summary': {
            'total_slots': len(slots),
            'successful_matches': len(items),
            'fallback_used_count': 0,
            'missing_count': len(missing),
        },
        'selected_items': sorted(items, key=lambda it: it.get('slot_number', 0)),
        'missing_items': missing,
    }


def empty_manifest() -> dict:
    return {
        'selection_summary': {
            'total_slots': 0,
            'successful_matches': 0,
            'fallback_used_count': 0,
            'missing_count': 0,
        },
        'selected_items': [],
        'missing_items': [],
    }


def merge_selection_manifests(
    non_sim: Optional[dict],
    sim: Optional[dict],
) -> dict:
    """
    Merges the independent Non-Sim and Sim track manifests by slot_number.
    Slot numbers are unique across tracks (they come from one quota manifest),
    so a simple sort by slot_number is a stable deterministic merge.
    """
    a = non_sim or empty_manifest()
    b = sim or empty_manifest()
    selected = [*(a.get('selected_items', [])), *(b.get('selected_items', []))]
    missing = [*(a.get('missing_items', [])), *(b.get('missing_items', []))]
    selected = sorted(selected, key=lambda it: it.get('slot_number', 0))
    missing = sorted(missing, key=lambda it: it.get('slot_number', 0))
    return {
        'selection_summary': {
            'total_slots': len(selected) + len(missing),
            'successful_matches': len(selected),
            'fallback_used_count': (
                (a.get('selection_summary', {}) or {}).get('fallback_used_count', 0)
                + (b.get('selection_summary', {}) or {}).get('fallback_used_count', 0)
            ),
            'missing_count': len(missing),
        },
        'selected_items': selected,
        'missing_items': missing,
    }


def build_sim_track_inputs(
    topic_files: list[dict],
    sim_slots: list[dict],
    resolved_topics: dict,
) -> tuple[list[dict], list[int]]:
    """
    Prepares the sim track: pairs each sim slot with a README (when available).

    Returns:
        (slots_with_readmes, missing_slot_numbers)
    Each entry in slots_with_readmes is {'slot': <quota slot dict>,
                                         'readme': <readme dict>}.
    """
    slots_with_readmes: list[dict] = []
    missing_numbers: list[int] = []
    for slot in sim_slots:
        num = slot.get('slot_number')
        if not isinstance(num, int):
            continue
        resolved = (resolved_topics or {}).get(num, '') or slot.get('topic', '')
        readme = resolve_readme(topic_files, resolved)
        if readme is None:
            missing_numbers.append(num)
        else:
            slots_with_readmes.append({'slot': slot, 'readme': readme})
    return slots_with_readmes, sorted(missing_numbers)


def build_sim_prompt(
    slot: dict,
    readme: dict,
    desired_type: str,
    resolved_topic: str,
) -> str:
    """Formats the per-slot prompt for the sim-question-generator agent."""
    from .tag_mapping import map_slot_tags

    q_type, _fmt = map_slot_tags(
        slot.get('slot_objective', ''),
        slot.get('style_constraint', ''),
        requested_format='Sim',
    )
    use_type = desired_type or q_type
    from .prompts import MATH_NOTATION_SPEC
    return (
        "Author ONE simulation-based question for a diagnostic quiz slot.\n"
        "\n"
        "=== SLOT PROFILE ===\n"
        f"slot_number: {slot.get('slot_number')}\n"
        f"objective_type: {slot.get('objective_type', '')}\n"
        f"topic: {resolved_topic}\n"
        f"target_issue: {slot.get('target_issue', '')}\n"
        f"desired_type: {use_type}\n"
        "\n"
        "=== SIMULATION README (the student runs this simulation) ===\n"
        f"{readme.get('content', '').strip()}\n"
        "\n"
        + MATH_NOTATION_SPEC + "\n"
        "Return ONLY a JSON object:\n"
        "{\n"
        '  "slot_number": <int>,\n'
        '  "question": {\n'
        '    "text": "<question stem; exact numeric expectations from the README>",\n'
        '    "type": "<' + '/'.join(sorted(VALID_QUESTION_TYPES)) + '>",\n'
        '    "options": ["A....", "B....", "C....", "D...."],\n'
        '    "correct_answer": "<expected answer matching the README>",\n'
        '    "subject": "<subject name>",\n'
        '    "topic": "<topic name>",\n'
        '    "sim_name": "' + str(readme.get('name', '')) + '",\n'
        '    "sim_instruction": "<what to set/run in the simulation before answering>"\n'
        "  },\n"
        '  "objective_type": "<same as slot objective_type>",\n'
        '  "match_confidence": "high|medium|low",\n'
        '  "selection_rationale": "<why this question fits the slot>"\n'
        "}\n"
    )