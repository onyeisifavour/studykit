"""
dev_test_agent2.py

Standalone verification harness for the Agent 2 pipeline (2a → tag mapping →
2c) plus the file retriever, run directly against a tagged question bank
before Agents 3-5 exist. Backs Issue #2 (Option B).

Prerequisites:
  - opencode CLI installed, authenticated, and agents registered:
      agent2a-topic-resolver
      agent2c-fallback-builder
      diagnostic-quota-planner (not used here, but part of the pipeline)
  - the target folder has tagged question_bank.txt + answer_bank.txt

Usage:
    python dev_test_agent2.py [path/to/topic_folder]

Exit code 0 = pipeline produced a valid query spec manifest + candidate pool.
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
from main_app.manifest_validator import validate_candidate_pool


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
    result: dict = {}
    failure: dict = {}

    def on_result(manifest: dict) -> None:
        result['manifest'] = manifest
        done.set()

    def on_error(err: str) -> None:
        failure['msg'] = err
        done.set()

    print("=== Agent 2 pipeline (2a → tag mapping → 2c) ===")
    runner.call_query_specifier(
        quota_manifest=quota_manifest,
        topic_files=topic_files,
        on_result=on_result,
        on_error=on_error,
    )
    done.wait(timeout=600)

    if 'msg' in failure:
        print("Agent 2 failed:")
        print(failure['msg'])
        return 1

    manifest = result['manifest']
    print(json.dumps(manifest, indent=2))

    print("\n=== File retriever ===")
    pool = retrieve_candidates(manifest, topic_files)
    pool_errors = validate_candidate_pool(pool)
    if pool_errors:
        print("Candidate pool invalid:")
        for e in pool_errors:
            print("  -", e)
        return 1

    for slot, candidates in sorted(pool.items()):
        print(f"\nSlot {slot}: {len(candidates)} candidate(s)")
        for c in candidates[:3]:
            snippet = c['question_text'][:80].replace('\n', ' ')
            print(f"  - [{c['tier']}] {snippet}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
