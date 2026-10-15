"""
dev_test_agent4.py

Standalone verification harness for the Agent 4 pipeline (4a pacing arc →
4b bucket/sort → 4c gateway/group → 4d manifest), chaining the full upstream
path: Agent 2 (2a → tag mapping → 2c) → file retriever → Agent 3 → Agent 4.

Prerequisites:
  - opencode CLI installed, authenticated, and agents registered:
      agent2a-topic-resolver
      agent2c-fallback-builder
      agent3b-candidate-selector
      agent4a-pacing-arc
  - the target folder has tagged question_bank.txt + answer_bank.txt

Usage:
    python dev_test_agent4.py [path/to/topic_folder]        # live chain
    python dev_test_agent4.py --mock                         # offline, synthetic

Exit code 0 = pipeline produced a valid sequenced quiz manifest that converts
into a ready-to-play question list.
"""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from main_app.agent_runner import AgentRunner
from main_app.api_client import CLIBridgeClient
from main_app.file_retriever import retrieve_candidates
from main_app.library_scanner import load_selected_topics
from main_app.manifest_validator import (
    validate_candidate_pool,
    validate_selected_items,
    validate_sequenced_quiz,
)
from main_app.question_generator import build_questions_from_sequence
from main_app.sequencer import build_ordered_sequence


def _mock_selection_manifest() -> dict:
    """Synthetic selected-items manifest for the offline functional test."""
    def q(slot, text, q_type, obj, conf, topic='Limits'):
        return {
            'slot_number': slot,
            'selected_question': {
                'text': text,
                'type': q_type,
                'subject': 'Math',
                'topic': topic,
                'format': 'Non-Sim',
                'options': ['A', 'B', 'C', 'D'] if q_type == 'MCQ' else [],
                'correct_answer': 'answer text',
            },
            'objective_type': obj,
            'source': 'bank',
            'match_confidence': conf,
        }

    return {
        'selection_summary': {
            'total_slots': 5, 'successful_matches': 5,
            'fallback_used_count': 0, 'missing_count': 0,
        },
        'selected_items': [
            q(1, 'Very long prerequisite theory question about epsilon definitions.',
              'Theory', 'prerequisite_repair', 'low'),
            q(2, 'Short conceptual MCQ about the limit definition.', 'MCQ',
              'conceptual_gap', 'high'),
            q(3, 'Medium conceptual MCQ about limits.', 'MCQ',
              'conceptual_gap', 'medium'),
            q(4, 'Long theory transfer question about l\'Hopital.', 'Theory',
              'transfer_mechanism', 'high'),
            q(5, 'Short synthesis MCQ about asymptotic behaviour.', 'MCQ',
              'synthesis_elevation', 'high'),
        ],
        'missing_items': [],
    }


def _check_sequenced(manifest: dict) -> list[str]:
    """Validates the sequenced manifest and prints the resulting quiz."""
    errors = validate_sequenced_quiz(manifest)
    if not errors:
        questions = build_questions_from_sequence(manifest)
        print("\n=== Quiz-ready question list ===")
        for gq in questions:
            print(f"Q{gq.number} [{gq.section}|{gq.q_type}] {gq.question_text[:60]}")
    return errors


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == '--mock':
        print("=== Functional test (offline, synthetic manifest) ===")
        manifest = build_ordered_sequence(
            _mock_selection_manifest()['selected_items'],
            {
                'pacing_strategy': 'Balanced Arc',
                'target_cognitive_flow': 'warm-up -> repair -> core -> transfer',
                'stage_sequence': [
                    {'stage': 'warm_up', 'position_range': [1, 1]},
                    {'stage': 'prerequisite_repair', 'position_range': [2, 2]},
                    {'stage': 'core_concept_gap', 'position_range': [3, 4]},
                    {'stage': 'transfer_elevation', 'position_range': [5, 6]},
                ],
            },
        )
        print(json.dumps(manifest, indent=2))
        errors = _check_sequenced(manifest)
        if errors:
            print("Sequenced quiz invalid:\n" + "\n".join(f"  - {e}" for e in errors))
            return 1
        stages = [e['pacing_stage'] for e in manifest['ordered_quiz_sequence']]
        print(f"\nPacing stages in order: {stages}")
        if stages[0] != 'Warm-up / Confidence Anchor':
            print("FAIL: first question is not the warm-up gateway.")
            return 1
        return 0

    folder = sys.argv[1] if len(sys.argv) > 1 else 'X/physics/topicfolder1'
    if not Path(folder).exists():
        print(f"Folder not found: {folder}")
        return 1

    topic_files = load_selected_topics([str(Path(folder).resolve())])
    if not topic_files:
        print("No valid topic loaded (needs question_bank.txt + answer_bank.txt).")
        return 1

    quota_manifest = {
        "quiz_metadata": {"total_questions": 2, "primary_objective": "harness test"},
        "slot_allocations": [
            {
                "slot_number": 1,
                "objective_type": "prerequisite_repair",
                "topic": Path(folder).name,
                "target_issue": "base conversion error",
                "style_constraint": "calculation",
            },
            {
                "slot_number": 2,
                "objective_type": "conceptual_gap",
                "topic": Path(folder).name,
                "target_issue": "irrational numbers",
                "style_constraint": "none",
            },
        ],
    }

    runner = AgentRunner(CLIBridgeClient())
    state: dict = {}
    failure: dict = {}

    def fail(msg: str) -> int:
        print(msg)
        return 1

    # ── Stage 1: Agent 2 → file retriever ────────────────────────────────────
    print("=== Agent 2 pipeline (2a → tag mapping → 2c) ===")
    spec_done = threading.Event()

    def on_spec_result(manifest: dict) -> None:
        state['spec'] = manifest
        spec_done.set()

    def on_spec_error(err: str) -> None:
        failure['msg'] = err
        spec_done.set()

    runner.call_query_specifier(
        quota_manifest=quota_manifest,
        topic_files=topic_files,
        on_result=on_spec_result,
        on_error=on_spec_error,
    )
    if not spec_done.wait(timeout=600):
        return fail("Timed out waiting for Agent 2.")
    if 'msg' in failure:
        return fail(f"Agent 2 failed:\n{failure['msg']}")

    print("\n=== File retriever ===")
    pool = retrieve_candidates(state['spec'], topic_files)
    pool_errors = validate_candidate_pool(pool)
    if pool_errors:
        return fail("Candidate pool invalid:\n" + "\n".join(f"  - {e}" for e in pool_errors))
    for slot, candidates in sorted(pool.items()):
        print(f"Slot {slot}: {len(candidates)} candidate(s)")

    # ── Stage 2: Agent 3 (candidate selector) ────────────────────────────────
    print("\n=== Agent 3 pipeline (3a → 3b → 3c → 3d) ===")
    sel_done = threading.Event()

    def on_sel_result(manifest: dict) -> None:
        state['selection'] = manifest
        sel_done.set()

    def on_sel_error(err: str) -> None:
        failure['msg'] = err
        sel_done.set()

    runner.call_candidate_selector(
        quota_manifest=quota_manifest,
        candidate_pool=pool,
        background_reports={},
        on_result=on_sel_result,
        on_error=on_sel_error,
    )
    if not sel_done.wait(timeout=600):
        return fail("Timed out waiting for Agent 3.")
    if 'msg' in failure:
        return fail(f"Agent 3 failed:\n{failure['msg']}")

    # ── Stage 3: Agent 4 (pedagogical sequence builder) ─────────────────────
    print("\n=== Agent 4 pipeline (4a → 4b → 4c → 4d) ===")
    seq_done = threading.Event()

    def on_seq_result(manifest: dict) -> None:
        state['sequence'] = manifest
        seq_done.set()

    def on_seq_error(err: str) -> None:
        failure['msg'] = err
        seq_done.set()

    runner.call_sequencer(
        selection_manifest=state['selection'],
        background_reports={},
        on_result=on_seq_result,
        on_error=on_seq_error,
    )
    if not seq_done.wait(timeout=600):
        return fail("Timed out waiting for Agent 4.")
    if 'msg' in failure:
        return fail(f"Agent 4 failed:\n{failure['msg']}")

    manifest = state['sequence']
    print("\n=== Sequenced quiz manifest ===")
    print(json.dumps(manifest, indent=2))

    errors = _check_sequenced(manifest)
    if errors:
        return fail("Sequenced quiz invalid:\n" + "\n".join(f"  - {e}" for e in errors))

    meta = manifest.get('sequence_metadata', {})
    print(f"\nSummary: {meta.get('total_questions')} sequenced, "
          f"strategy '{meta.get('pacing_strategy')}'")
    return 0


if __name__ == '__main__':
    sys.exit(main())
