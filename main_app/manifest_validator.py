"""
manifest_validator.py

Per-stage schema validation for the agent pipeline manifests.

Each validator inspects an already-parsed JSON structure (from _extract_json)
and returns a list of human-readable error strings. An empty list means the
manifest is valid and safe to store or consume. Validators run BEFORE a
manifest is persisted or handed to a downstream step, so structural problems
surface as descriptive errors instead of silent empty results.

Contracts mirror the blueprint schemas:
  - quota manifest      (Agent 1)      -> validate_quota_manifest
  - file query spec     (Agent 2, 2d)  -> validate_query_spec_manifest
  - candidate pool      (file retriever)-> validate_candidate_pool
  - selected items      (Agent 3)      -> validate_selected_items
  - sequenced quiz      (Agent 4)      -> validate_sequenced_quiz
"""

from __future__ import annotations

from typing import Any

# ── Allowed enums ─────────────────────────────────────────────────────────────

VALID_OBJECTIVE_TYPES = {
    'prerequisite_repair',
    'conceptual_gap',
    'transfer_mechanism',
    'synthesis_elevation',
}

VALID_TIERS = ('tier_1_exact', 'tier_2_topic_fallback', 'tier_3_type_relaxation')

TIER_REQUIRED_KEYS = ('subject', 'topic', 'type', 'format')

VALID_QUESTION_TYPES = {'MCQ', 'Hybrid', 'Theory'}

VALID_FORMATS = {'Non-Sim', 'Sim'}

VALID_SOURCES = {'bank', 'sim_generated'}

VALID_CONFIDENCE = {'high', 'medium', 'low'}


# ── Quota manifest (Agent 1) ──────────────────────────────────────────────────

def validate_quota_manifest(m: Any) -> list[str]:
    """Validates the Agent 1 quota breakdown manifest."""
    errors: list[str] = []

    if not isinstance(m, dict):
        return ['Quota manifest must be a JSON object']

    meta = m.get('quiz_metadata')
    if not isinstance(meta, dict):
        errors.append('Missing quiz_metadata object')
    else:
        total = meta.get('total_questions')
        if not isinstance(total, int) or total <= 0:
            errors.append('quiz_metadata.total_questions must be a positive integer')

    slots = m.get('slot_allocations')
    if not isinstance(slots, list):
        errors.append('Missing slot_allocations array')
        return errors

    total = meta.get('total_questions') if isinstance(meta, dict) else None
    if isinstance(total, int) and len(slots) != total:
        errors.append(
            f'slot_allocations has {len(slots)} entries but total_questions is {total}'
        )

    seen_numbers: set[int] = set()
    for i, slot in enumerate(slots):
        label = f'slot_allocations[{i}]'
        if not isinstance(slot, dict):
            errors.append(f'{label} must be an object')
            continue

        num = slot.get('slot_number')
        if not isinstance(num, int):
            errors.append(f'{label}.slot_number must be an integer')
        else:
            if num in seen_numbers:
                errors.append(f'{label}.slot_number {num} is duplicated')
            seen_numbers.add(num)

        otype = slot.get('objective_type')
        if not isinstance(otype, str) or otype not in VALID_OBJECTIVE_TYPES:
            errors.append(
                f'{label}.objective_type must be one of '
                f'{sorted(VALID_OBJECTIVE_TYPES)}'
            )

        topic = slot.get('topic')
        if not isinstance(topic, str) or not topic.strip():
            errors.append(f'{label}.topic must be a non-empty string')

        issue = slot.get('target_issue')
        if not isinstance(issue, str) or not issue.strip():
            errors.append(f'{label}.target_issue must be a non-empty string')

        fmt = slot.get('format')
        if fmt is not None and (
            not isinstance(fmt, str) or fmt not in VALID_FORMATS
        ):
            errors.append(
                f'{label}.format must be one of {sorted(VALID_FORMATS)}'
            )

    return errors


# ── Resolved slots (Agent 2, step 2a) ─────────────────────────────────────────

def validate_resolved_slots(slots: Any) -> list[str]:
    """
    Validates the step 2a output: the topic-resolution list.

    Shape: [ {slot_number, slot_objective, resolved_topic, resolved_subject,
              target_issue, keywords}, ... ]
    """
    errors: list[str] = []

    if not isinstance(slots, list):
        return ['Resolved slots must be a JSON array']

    seen_numbers: set[int] = set()
    for i, slot in enumerate(slots):
        label = f'resolved_slots[{i}]'
        if not isinstance(slot, dict):
            errors.append(f'{label} must be an object')
            continue

        num = slot.get('slot_number')
        if not isinstance(num, int):
            errors.append(f'{label}.slot_number must be an integer')
        else:
            if num in seen_numbers:
                errors.append(f'{label}.slot_number {num} is duplicated')
            seen_numbers.add(num)

        obj = slot.get('slot_objective')
        if not isinstance(obj, str) or not obj.strip():
            errors.append(f'{label}.slot_objective must be a non-empty string')

        for key in ('resolved_topic', 'resolved_subject', 'target_issue'):
            value = slot.get(key)
            if not isinstance(value, str) or not value.strip():
                errors.append(f'{label}.{key} must be a non-empty string')

        kw = slot.get('keywords')
        if not isinstance(kw, list) or not all(isinstance(k, str) for k in kw):
            errors.append(f'{label}.keywords must be a list of strings')

    return errors


# ── File query spec manifest (Agent 2) ────────────────────────────────────────

def validate_query_spec_manifest(m: Any) -> list[str]:
    """Validates the Agent 2 file query spec manifest (search tiers per slot)."""
    errors: list[str] = []

    if not isinstance(m, dict):
        return ['Query spec manifest must be a JSON object']

    specs = m.get('file_query_specs')
    if not isinstance(specs, list):
        errors.append('Missing file_query_specs array')
        return errors

    for i, spec in enumerate(specs):
        label = f'file_query_specs[{i}]'
        if not isinstance(spec, dict):
            errors.append(f'{label} must be an object')
            continue

        num = spec.get('slot_number')
        if not isinstance(num, int):
            errors.append(f'{label}.slot_number must be an integer')

        obj = spec.get('slot_objective')
        if not isinstance(obj, str) or not obj.strip():
            errors.append(f'{label}.slot_objective must be a non-empty string')

        tiers = spec.get('search_tiers')
        if not isinstance(tiers, dict):
            errors.append(f'{label}.search_tiers must be an object')
            continue

        for tier_key in VALID_TIERS:
            tier = tiers.get(tier_key)
            if not isinstance(tier, dict):
                errors.append(f'{label}.search_tiers missing {tier_key} object')
                continue
            for key in TIER_REQUIRED_KEYS:
                value = tier.get(key)
                if not isinstance(value, str) or not value.strip():
                    errors.append(
                        f'{label}.search_tiers.{tier_key}.{key} '
                        'must be a non-empty string'
                    )

    return errors


# ── Candidate pool (file retriever) ───────────────────────────────────────────

def validate_candidate_pool(pool: Any) -> list[str]:
    """
    Validates the candidate pool produced by the file retriever.

    Shape: { slot_number: [candidate_dict, ...] }
    An empty candidate list per slot is legitimate (the slot is flagged
    MISSING downstream), so only structure is checked.
    """
    errors: list[str] = []

    if not isinstance(pool, dict):
        return ['Candidate pool must be a JSON object keyed by slot_number']

    for key, candidates in pool.items():
        label = f'candidate_pool slot {key!r}'
        if isinstance(key, str) and key.isdigit():
            key = int(key)
        if not isinstance(key, int):
            errors.append(f'{label} key must be an integer slot number')
            continue
        if not isinstance(candidates, list):
            errors.append(f'{label} must be a list of candidates')
            continue
        for j, cand in enumerate(candidates):
            if not isinstance(cand, dict):
                errors.append(f'{label} candidate[{j}] must be an object')
                continue
            q_text = cand.get('question_text')
            if not isinstance(q_text, str) or not q_text.strip():
                errors.append(f'{label} candidate[{j}].question_text '
                              'must be a non-empty string')
            tags = cand.get('tags')
            if not isinstance(tags, dict):
                errors.append(f'{label} candidate[{j}].tags must be an object')

    return errors


# ── Selected items manifest (Agent 3) ─────────────────────────────────────────

def validate_selected_items(m: Any) -> list[str]:
    """
    Validates the Agent 3 selected-items manifest.

    Shape:
        {
          "selected_items": [
            {
              "slot_number": int,
              "selected_question": {
                "text": str,
                "type": "MCQ"|"Hybrid"|"Theory",
                "subject": str,
                "topic": str,
                "format": "Non-Sim"|"Sim",
                "options": [str, ...],        # empty for non-MCQ
                "correct_answer": str
              },
              "objective_type": str,
              "source": "bank"|"sim_generated",
              "match_confidence": "high"|"medium"|"low",   # optional
              "selection_rationale": str                    # optional
            }
          ],
          "missing_items": [ {slot_number, reason}, ... ]
        }

    match_confidence / selection_rationale are optional because single-
    candidate slots are auto-selected deterministically by code (step 3-4)
    without the 3b agent.
    """
    errors: list[str] = []

    if not isinstance(m, dict):
        return ['Selected items manifest must be a JSON object']

    items = m.get('selected_items')
    if not isinstance(items, list):
        errors.append('Missing selected_items array')
        return errors

    seen_numbers: set[int] = set()
    for i, item in enumerate(items):
        label = f'selected_items[{i}]'
        if not isinstance(item, dict):
            errors.append(f'{label} must be an object')
            continue

        num = item.get('slot_number')
        if not isinstance(num, int):
            errors.append(f'{label}.slot_number must be an integer')
        else:
            if num in seen_numbers:
                errors.append(f'{label}.slot_number {num} is duplicated')
            seen_numbers.add(num)

        obj = item.get('objective_type')
        if not isinstance(obj, str) or obj not in VALID_OBJECTIVE_TYPES:
            errors.append(
                f'{label}.objective_type must be one of '
                f'{sorted(VALID_OBJECTIVE_TYPES)}'
            )

        src = item.get('source')
        if not isinstance(src, str) or src not in VALID_SOURCES:
            errors.append(
                f'{label}.source must be one of {sorted(VALID_SOURCES)}'
            )

        conf = item.get('match_confidence')
        if conf is not None and (
            not isinstance(conf, str) or conf not in VALID_CONFIDENCE
        ):
            errors.append(
                f'{label}.match_confidence must be one of '
                f'{sorted(VALID_CONFIDENCE)}'
            )

        rationale = item.get('selection_rationale')
        if rationale is not None and (
            not isinstance(rationale, str) or not rationale.strip()
        ):
            errors.append(f'{label}.selection_rationale must be a non-empty string')

        q = item.get('selected_question')
        if not isinstance(q, dict):
            errors.append(f'{label}.selected_question must be an object')
            continue

        _validate_selected_question(q, f'{label}.selected_question', errors)

    missing = m.get('missing_items')
    if missing is not None and not isinstance(missing, list):
        errors.append('missing_items must be an array')

    return errors


def _validate_selected_question(q: dict, label: str, errors: list[str]) -> None:
    """Validates the body of a selected question, shared by Agents 3 and 4."""
    text = q.get('text')
    if not isinstance(text, str) or not text.strip():
        errors.append(f'{label}.text must be a non-empty string')

    q_type = q.get('type')
    if not isinstance(q_type, str) or q_type not in VALID_QUESTION_TYPES:
        errors.append(f'{label}.type must be one of {sorted(VALID_QUESTION_TYPES)}')

    for key in ('subject', 'topic'):
        value = q.get(key)
        if not isinstance(value, str) or not value.strip():
            errors.append(f'{label}.{key} must be a non-empty string')

    fmt = q.get('format')
    if not isinstance(fmt, str) or fmt not in VALID_FORMATS:
        errors.append(f'{label}.format must be one of {sorted(VALID_FORMATS)}')

    answer = q.get('correct_answer')
    if not isinstance(answer, str) or not answer.strip():
        errors.append(f'{label}.correct_answer must be a non-empty string')

    opts = q.get('options')
    if opts is not None and (
        not isinstance(opts, list) or not all(isinstance(o, str) for o in opts)
    ):
        errors.append(f'{label}.options must be a list of strings')


# ── Sequenced quiz manifest (Agent 4) ─────────────────────────────────────────

def validate_sequenced_quiz(m: Any) -> list[str]:
    """
    Validates the Agent 4 sequenced-quiz manifest.

    Shape:
        {
          "sequence_metadata": {
            "total_questions": int,
            "pacing_strategy": str,
            "target_cognitive_flow": str
          },
          "ordered_quiz_sequence": [
            {
              "sequence_index": int,
              "question": { text/type/subject/topic/format/options/correct_answer },
              "objective_type": str,
              "source": "bank"|"sim_generated",
              "pacing_stage": str,
              "position_rationale": str
            }
          ]
        }
    """
    errors: list[str] = []

    if not isinstance(m, dict):
        return ['Sequenced quiz manifest must be a JSON object']

    meta = m.get('sequence_metadata')
    if not isinstance(meta, dict):
        errors.append('Missing sequence_metadata object')
    else:
        total = meta.get('total_questions')
        if not isinstance(total, int) or total < 0:
            errors.append('sequence_metadata.total_questions must be a non-negative integer')
        for key in ('pacing_strategy', 'target_cognitive_flow'):
            value = meta.get(key)
            if not isinstance(value, str):
                errors.append(f'sequence_metadata.{key} must be a string')

    seq = m.get('ordered_quiz_sequence')
    if not isinstance(seq, list):
        errors.append('Missing ordered_quiz_sequence array')
        return errors

    seen_indices: set[int] = set()
    for i, entry in enumerate(seq):
        label = f'ordered_quiz_sequence[{i}]'
        if not isinstance(entry, dict):
            errors.append(f'{label} must be an object')
            continue

        idx = entry.get('sequence_index')
        if not isinstance(idx, int):
            errors.append(f'{label}.sequence_index must be an integer')
        else:
            if idx in seen_indices:
                errors.append(f'{label}.sequence_index {idx} is duplicated')
            seen_indices.add(idx)

        obj = entry.get('objective_type')
        if not isinstance(obj, str) or obj not in VALID_OBJECTIVE_TYPES:
            errors.append(
                f'{label}.objective_type must be one of '
                f'{sorted(VALID_OBJECTIVE_TYPES)}'
            )

        src = entry.get('source')
        if not isinstance(src, str) or src not in VALID_SOURCES:
            errors.append(f'{label}.source must be one of {sorted(VALID_SOURCES)}')

        stage = entry.get('pacing_stage')
        if not isinstance(stage, str) or not stage.strip():
            errors.append(f'{label}.pacing_stage must be a non-empty string')

        rationale = entry.get('position_rationale')
        if not isinstance(rationale, str) or not rationale.strip():
            errors.append(f'{label}.position_rationale must be a non-empty string')

        q = entry.get('question')
        if not isinstance(q, dict):
            errors.append(f'{label}.question must be an object')
            continue

        _validate_selected_question(q, f'{label}.question', errors)

    return errors
