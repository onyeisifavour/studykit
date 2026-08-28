"""
dev_test_agent5.py

Standalone verification harness for the Agent 5 pipeline (Step 1 structural
code audit → 5b/5c AI audits in parallel → Step 4 decision gate → sanitised
payload), chaining the full upstream path: Agent 2 → file retriever → Agent 3
→ Agent 4 → Agent 5.

Prerequisites:
  - opencode CLI installed, authenticated, and agents registered:
      agent2a-topic-resolver, agent2c-fallback-builder,
      agent3b-candidate-selector, agent4a-pacing-arc,
      agent5b-diagnostic-audit, agent5c-preference-audit
  - the target folder has tagged question_bank.txt + answer_bank.txt

Usage:
    python dev_test_agent5.py [path/to/topic_folder]        # live chain
    python dev_test_agent5.py --mock                         # offline, synthetic

Exit code 0 = pipeline produced an audited, sanitised production payload.
"""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from main_app.agent_runner import AgentRunner
from main_app.api_client import CLIBridgeClient
from main_app.compliance_auditor import (
    assemble_audit_result,
    audit_structural,
    build_production_payload,
    rebuild_sequence_manifest,
)
from main_app.file_retriever import retrieve_candidates
from main_app.library_scanner import load_selected_topics
from main_app.manifest_validator import (
    validate_candidate_pool,
    validate_selected_items,
    validate_sequenced_quiz,
)
from main_app.sequencer import build_ordered_sequence


def _mock_sequenced_manifest() -> dict:
    """A valid sequenced manifest built through the real sequencer."""
    from dev_test_agent4 import _mock_selection_manifest

    return build_ordered_sequence(
        _mock_selection_manifest()['selected_items'],
        {'pacing_strategy': 'Balanced Arc', 'target_cognitive_flow': ''},
    )


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == '--mock':
        print("=== Functional test (offline, synthetic manifest) ===")
        manifest = _mock_sequenced_manifest()
        errors = validate_sequenced_quiz(manifest)
        if errors:
            print("Sequenced manifest invalid:\n" + "\n".join(f"  - {e}" for e in errors))
            return 1

        structural = audit_structural(manifest)
        print("\n=== Step 1: structural audit ===")
        for c in structural:
            print(f"  [{c['status']}] {c['check']} — {c['evidence']}")

        diag = {'verdict': 'PASS', 'checks': [
            {'check': 'prerequisite_safety_net', 'status': 'PASS',
             'evidence': 'prerequisite_repair question present', 'missing': None},
        ]}
        pref = {'verdict': 'PASS', 'checks': [
            {'check': 'topic_preference', 'status': 'NA',
             'interpreted_request': 'no topic named', 'conflict_note': None},
        ]}
        result = assemble_audit_result(structural, diag, pref, missing_items=[])
        if result['audit_status'] != 'PASSED':
            print(f"FAIL: expected PASSED, got {result['audit_status']}")
            return 1

        payload = build_production_payload(manifest)
        rebuilt = rebuild_sequence_manifest(payload)
        roundtrip = validate_sequenced_quiz(rebuilt)
        if roundtrip:
            print("Payload round-trip invalid:\n"
                  + "\n".join(f"  - {e}" for e in roundtrip))
            return 1

        print("\n=== Step 4: sanitised payload (round-trips to a valid quiz) ===")
        print(json.dumps(payload, indent=2))
        print(f"\nSummary: {payload['total_questions']} questions, "
              f"status {result['audit_status']}")
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

    # ── Stage 2: Agent 3 ─────────────────────────────────────────────────────
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

    # ── Stage 3: Agent 4 ─────────────────────────────────────────────────────
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

    # ── Stage 4: Agent 5 (compliance audit) ─────────────────────────────────
    print("\n=== Agent 5 pipeline (1 code audit → 5b/5c in parallel → gate) ===")
    audit_done = threading.Event()

    def on_audit_result(result: dict, payload: dict) -> None:
        state['audit'] = result
        state['payload'] = payload
        audit_done.set()

    def on_audit_error(err: str) -> None:
        failure['msg'] = err
        audit_done.set()

    runner.call_compliance_audit(
        sequence_manifest=state['sequence'],
        background_reports={},
        user_request="2 questions on chemistry, focus on the definition",
        missing_items=state['selection'].get('missing_items', []),
        on_result=on_audit_result,
        on_error=on_audit_error,
    )
    if not audit_done.wait(timeout=600):
        return fail("Timed out waiting for Agent 5.")
    if 'msg' in failure:
        return fail(f"Agent 5 failed:\n{failure['msg']}")

    print("\n=== Compliance audit result ===")
    print(json.dumps(state['audit'], indent=2))
    print("\n=== Sanitised production payload ===")
    print(json.dumps(state['payload'], indent=2))

    if state['audit']['audit_status'] != 'PASSED':
        return fail("Audit did not PASS.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
