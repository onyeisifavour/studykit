"""
compliance_auditor.py

Deterministic steps of Agent 5 (Compliance Auditor): the structural audit
(Step 1) and the decision gate / payload sanitisation (Step 4). The two AI
judgment steps (5b diagnostic alignment, 5c user-preference compliance) are
separate primary agents driven by agent_runner.call_compliance_audit().

    Step 1: audit_structural()   — deterministic checks: length, uniqueness,
                                   field integrity, tag consistency, sim-set
                                   contiguity. Returns per-check verdicts.
    Step 2: agent5b (AI)         — diagnostic alignment audit
    Step 3: agent5c (AI)         — user-preference compliance audit
    Step 4: assemble_audit_result() — decision gate (PASSED/FAILED) +
                                   build_production_payload() for PASSED.

This module only inspects and re-forms the manifest; it never edits question
text. Decision gate is pure code so the PASS/FAIL routing is auditable.
"""

from __future__ import annotations

from typing import Any

VALID_QUESTION_TYPES = {'MCQ', 'Hybrid', 'Theory'}
VALID_FORMATS = {'Non-Sim', 'Sim'}


# ── Step 1: Structural & integrity audit (code) ──────────────────────────────

def audit_structural(manifest: dict) -> list[dict]:
    """
    Runs the deterministic Step-1 checks against the Agent 4 manifest.

    Returns a list of verdict dicts, one per check:
        {"check": str, "status": "PASS"|"FAIL", "evidence": str}
    """
    checks: list[dict] = []

    seq = manifest.get('ordered_quiz_sequence', [])
    meta = manifest.get('sequence_metadata', {})
    total = meta.get('total_questions') if isinstance(meta, dict) else None

    if not isinstance(seq, list):
        return [{
            'check': 'structure',
            'status': 'FAIL',
            'evidence': 'ordered_quiz_sequence is not an array',
        }]

    # ── Length check ──────────────────────────────────────────────────────────
    if isinstance(total, int) and len(seq) != total:
        checks.append({
            'check': 'length',
            'status': 'FAIL',
            'evidence': f'manifest has {len(seq)} questions but '
                        f'total_questions is {total}',
        })
    else:
        checks.append({
            'check': 'length',
            'status': 'PASS',
            'evidence': f'length matches total_questions ({len(seq)})',
        })

    # ── Unique item check ─────────────────────────────────────────────────────
    seen: set[str] = set()
    dupes: list[str] = []
    for i, entry in enumerate(seq):
        text = (entry.get('question', {}) if isinstance(entry, dict)
                else {}).get('text', '')
        key = text.strip().lower()
        if key and key in seen:
            dupes.append(f'position {i + 1}')
        if key:
            seen.add(key)
    if dupes:
        checks.append({
            'check': 'unique_items',
            'status': 'FAIL',
            'evidence': 'duplicate question text at: ' + ', '.join(dupes),
        })
    else:
        checks.append({
            'check': 'unique_items',
            'status': 'PASS',
            'evidence': f'{len(seq)} unique question texts',
        })

    # ── Field integrity + tag consistency + sim-set contiguity ────────────────
    field_failures: list[str] = []
    tag_failures: list[str] = []
    sim_set_positions: dict[tuple[str, str], list[int]] = {}

    for i, entry in enumerate(seq):
        label = f'position {i + 1}'
        if not isinstance(entry, dict) or not isinstance(entry.get('question'), dict):
            field_failures.append(f'{label}: missing question object')
            continue
        q = entry['question']

        if not isinstance(q.get('text'), str) or not q['text'].strip():
            field_failures.append(f'{label}: empty question text')
        if not isinstance(q.get('correct_answer'), str) or not q['correct_answer'].strip():
            field_failures.append(f'{label}: missing correct_answer')
        if q.get('type') not in VALID_QUESTION_TYPES:
            field_failures.append(f'{label}: invalid type {q.get("type")!r}')
        if q.get('type') == 'MCQ' and not isinstance(q.get('options'), list):
            field_failures.append(f'{label}: MCQ missing options list')

        for tag in ('subject', 'topic'):
            if not isinstance(q.get(tag), str) or not q[tag].strip():
                tag_failures.append(f'{label}: missing {tag} tag')
        if q.get('format') not in VALID_FORMATS:
            tag_failures.append(f'{label}: invalid format {q.get("format")!r}')

        if q.get('format') == 'Sim':
            if not q.get('sim_name') or not q.get('sim_instruction'):
                tag_failures.append(f'{label}: Sim question missing sim tags')
            sim_set = q.get('sim_set')
            if sim_set:
                key = (str(q.get('sim_name', '')), str(sim_set))
                sim_set_positions.setdefault(key, []).append(i + 1)

    checks.append({
        'check': 'field_integrity',
        'status': 'PASS' if not field_failures else 'FAIL',
        'evidence': 'all fields complete' if not field_failures
                    else '; '.join(field_failures),
    })

    checks.append({
        'check': 'tag_consistency',
        'status': 'PASS' if not tag_failures else 'FAIL',
        'evidence': 'all tags present' if not tag_failures
                    else '; '.join(tag_failures),
    })

    split_sets: list[str] = []
    for key, positions in sim_set_positions.items():
        expected = list(range(positions[0], positions[-1] + 1))
        if positions != expected:
            split_sets.append(f'{key[0]} set {key[1]} at {positions}')
    checks.append({
        'check': 'sim_set_integrity',
        'status': 'PASS' if not split_sets else 'FAIL',
        'evidence': 'no sim sets split' if not split_sets
                    else 'split sim sets: ' + '; '.join(split_sets),
    })

    return checks


# ── Step 4: Decision gate (code) ──────────────────────────────────────────────

def assemble_audit_result(
    structural_checks: list[dict],
    diag_verdict: dict | None,
    pref_verdict: dict | None,
    missing_items: list[dict] | None = None,
) -> dict:
    """
    Combines the code audit + the two AI audits into the final result.

    Returns either a PASSED result (with the sanitised payload) or a FAILED
    result (with failure_reason + retry_instruction).
    """
    structural_ok = all(c.get('status') == 'PASS' for c in structural_checks)
    diag_ok = bool(diag_verdict) and diag_verdict.get('verdict') == 'PASS'
    pref_ok = bool(pref_verdict) and pref_verdict.get('verdict') == 'PASS'

    structural_failures = [c for c in structural_checks if c.get('status') != 'PASS']

    missing_note = None
    if missing_items:
        missing_note = {
            'proceed_with_reduced_count': True,
            'missing_slots': missing_items,
        }

    if structural_ok and diag_ok and pref_ok:
        return {
            'audit_status': 'PASSED',
            'audit_checks': {
                'structural': structural_checks,
                'diagnostic': diag_verdict,
                'preference': pref_verdict,
            },
            'missing_items_note': missing_note,
        }

    if structural_failures:
        reason = 'STRUCTURAL_AUDIT_FAILED'
        target = 'pipeline'
        action = 'Structural checks failed: ' + '; '.join(
            f"{c.get('check')} ({c.get('evidence')})" for c in structural_failures
        )
    elif not diag_ok:
        reason = 'DIAGNOSTIC_ALIGNMENT_FAILED'
        target = 'agent3b-candidate-selector'
        action = 'Diagnostic coverage incomplete: ' + str(
            diag_verdict or 'no 5b verdict'
        )
    else:
        reason = 'USER_PREFERENCE_COMPLIANCE_FAILED'
        target = 'agent4a-pacing-arc'
        action = 'User preference mismatch: ' + str(pref_verdict or 'no 5c verdict')

    return {
        'audit_status': 'FAILED',
        'failure_reason': reason,
        'audit_checks': {
            'structural': structural_checks,
            'diagnostic': diag_verdict,
            'preference': pref_verdict,
        },
        'retry_instruction': {
            'target_agent': target,
            'action': action,
        },
        'missing_items_note': missing_note,
    }


# ── Step 4 (PASSED): Sanitised production payload ─────────────────────────────

def build_production_payload(manifest: dict) -> dict:
    """
    Strips internal agent artefacts and returns the sanitised quiz payload.

    Per the decided policy, pacing metadata (pacing_stage, objective_type,
    position_rationale) is kept for the UI and future review features; agent
    selection internals are dropped.
    """
    seq = manifest.get('ordered_quiz_sequence', [])
    questions = []
    for i, entry in enumerate(seq, start=1):
        q = entry.get('question', {})
        questions.append({
            'position': i,
            'question_text': q.get('text', ''),
            'type': q.get('type', ''),
            'subject': q.get('subject', ''),
            'topic': q.get('topic', ''),
            'format': q.get('format', 'Non-Sim'),
            'options': q.get('options', []) or [],
            'correct_answer': q.get('correct_answer', ''),
            'sim_name': q.get('sim_name', ''),
            'sim_instruction': q.get('sim_instruction', ''),
            'objective_type': entry.get('objective_type', ''),
            'pacing_stage': entry.get('pacing_stage', ''),
            'position_rationale': entry.get('position_rationale', ''),
        })
    return {
        'total_questions': len(questions),
        'questions': questions,
    }


# ── Rebuild the manifest from a payload (for the quiz runtime) ───────────────

def rebuild_sequence_manifest(payload: dict) -> dict:
    """
    Inverse of build_production_payload(): converts the sanitised payload back
    into the ordered_quiz_sequence shape the question builder consumes.
    """
    questions = []
    for i, q in enumerate(payload.get('questions', []), start=1):
        questions.append({
            'sequence_index': i,
            'question': {
                'text': q.get('question_text', ''),
                'type': q.get('type', ''),
                'subject': q.get('subject', ''),
                'topic': q.get('topic', ''),
                'format': q.get('format', 'Non-Sim'),
                'options': q.get('options', []) or [],
                'correct_answer': q.get('correct_answer', ''),
                'sim_name': q.get('sim_name', ''),
                'sim_instruction': q.get('sim_instruction', ''),
            },
            'objective_type': q.get('objective_type', ''),
            'source': 'bank',
            'pacing_stage': q.get('pacing_stage', ''),
            'position_rationale': q.get('position_rationale', ''),
        })
    return {
        'sequence_metadata': {
            'total_questions': len(questions),
            'pacing_strategy': '',
            'target_cognitive_flow': '',
        },
        'ordered_quiz_sequence': questions,
    }
