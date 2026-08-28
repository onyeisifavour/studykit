"""
dev_test_agent3.py

Standalone verification harness for the Agent 3 pipeline (3a grouping →
3b candidate selection → 3c fallback → 3d manifest assembly), run directly
against a tagged question bank before Agent 4 exists. Chains the full
upstream path: Agent 2 (2a → tag mapping → 2c) → file retriever → Agent 3.

Prerequisites:
  - opencode CLI installed, authenticated, and agents registered:
      agent2a-topic-resolver
      agent2c-fallback-builder
      agent3b-candidate-selector
  - the target folder has tagged question_bank.txt + answer_bank.txt

Usage:
    python dev_test_agent3.py [path/to/topic_folder]

Exit code 0 = pipeline produced a valid query spec manifest + candidate pool
+ selected items manifest.
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
)


def main() -> int:
    folder = sys.argv[1] if len(sys.argv) > 1 else 'X/physics/topicfolder1'
    if not Path(folder).exists():
        print(f"Folder not found: {folder}")
        return 1

    topic_files = load_selected_topics([str(Path(folder).resolve())])
    if not topic_files:
        print("No valid topic loaded (needs question_bank.txt + answer_bank.txt).")
        return 1

    # Demo quota manifest: 2 slots against the sample topic.
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
    done = threading.Event()
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
        for c in candidates[:3]:
            snippet = c['question_text'][:80].replace('\n', ' ')
            print(f"  - [{c['tier']}] {snippet}")

    # ── Stage 2: Agent 3 (candidate selector) ────────────────────────────────
    print("\n=== Agent 3 pipeline (3a → 3b → 3c → 3d) ===")
    sel_done = threading.Event()

    def on_sel_result(manifest: dict) -> None:
        state['selection'] = manifest
        sel_done.set()

    def on_sel_error(err: str) -> None:
        failure['msg'] = err
        sel_done.set()

    # No diagnostic reports in the harness; the formatter degrades gracefully.
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

    manifest = state['selection']
    print("\n=== Selected items manifest ===")
    print(json.dumps(manifest, indent=2))

    sel_errors = validate_selected_items(manifest)
    if sel_errors:
        return fail("Selected items manifest invalid:\n"
                    + "\n".join(f"  - {e}" for e in sel_errors))

    summary = manifest.get('selection_summary', {})
    print(f"\nSummary: {summary.get('successful_matches')} selected, "
          f"{summary.get('missing_count')} missing, "
          f"{summary.get('fallback_used_count')} fallback tier(s)")
    return 0


if __name__ == '__main__':
    sys.exit(main())
