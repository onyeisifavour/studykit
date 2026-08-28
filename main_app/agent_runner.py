"""
agent_runner.py

High-level service for calling opencode agents. Manages:
- Agent calls with session persistence
- Message stacking for background models (network resilience)
- Main chat flow with topic context
- Background model parallel execution

Usage:
    runner = AgentRunner(cli_client)
    
    # First turn
    runner.call_main_chat(
        user_message="hi",
        topic_files=topic_files,
        prefs=prefs,
        on_result=lambda text: root.after(0, lambda: show_reply(text)),
        on_error=lambda err: root.after(0, lambda: show_error(err)),
    )
    
    # After user clicks Generate Quiz
    runner.resolve_pending_and_get_reports(
        on_complete=lambda reports: root.after(0, lambda: start_blueprint(reports))
    )
"""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor, Future
from pathlib import Path
from typing import Callable, Optional

from . import config
from .api_client import CLIBridgeClient
from .answer_matcher import split_mcq
from .manifest_validator import (
    validate_quota_manifest,
    validate_resolved_slots,
    validate_query_spec_manifest,
    validate_selected_items,
    validate_sequenced_quiz,
)
from . import sequencer
from .pipeline_errors import build_pipeline_error
from .tag_mapping import enrich_slots


# Agent name constants
AGENT_MAIN_CHAT = 'pre-quiz_main_chat'
AGENT_QUOTA_PLANNER = 'diagnostic-quota-planner'
AGENT_2A_TOPIC_RESOLVER = 'agent2a-topic-resolver'
AGENT_2C_FALLBACK_BUILDER = 'agent2c-fallback-builder'
AGENT_3B_CANDIDATE_SELECTOR = 'agent3b-candidate-selector'
AGENT_4A_PACING_ARC = 'agent4a-pacing-arc'
AGENT_5B_DIAGNOSTIC_AUDIT = 'agent5b-diagnostic-audit'
AGENT_5C_PREFERENCE_AUDIT = 'agent5c-preference-audit'
AGENT_BG_KNOWLEDGE = 'knowledge-graph-builder'
AGENT_BG_MECHANISM = 'mechanism-evaluator'
AGENT_BG_MISCONCEPTION = 'misconception-classifier'
AGENT_BG_DRILL = 'drill-recommender'

ALL_BG_AGENTS = [
    AGENT_BG_KNOWLEDGE,
    AGENT_BG_MECHANISM,
    AGENT_BG_MISCONCEPTION,
    AGENT_BG_DRILL,
]

# Every agent the app calls directly via the opencode CLI bridge.
PIPELINE_AGENTS = [
    AGENT_MAIN_CHAT,
    *ALL_BG_AGENTS,
    AGENT_QUOTA_PLANNER,
    AGENT_2A_TOPIC_RESOLVER,
    AGENT_2C_FALLBACK_BUILDER,
    AGENT_3B_CANDIDATE_SELECTOR,
    AGENT_4A_PACING_ARC,
    AGENT_5B_DIAGNOSTIC_AUDIT,
    AGENT_5C_PREFERENCE_AUDIT,
]

OPENCODE_CONFIG = Path.home() / '.config' / 'opencode' / 'opencode.json'


def check_registered_agents() -> list[str]:
    """
    Returns the list of pipeline agents NOT registered in the opencode config.

    Reads ~/.config/opencode/opencode.json; if the file is missing or corrupt,
    all agents are reported missing (the runtime probable-cause errors take over).
    """
    if not OPENCODE_CONFIG.exists():
        return list(PIPELINE_AGENTS)
    try:
        cfg = json.loads(OPENCODE_CONFIG.read_text(encoding='utf-8'))
    except Exception:
        return list(PIPELINE_AGENTS)
    registered = set((cfg.get('agent') or {}).keys())
    return [name for name in PIPELINE_AGENTS if name not in registered]


class AgentRunner:
    """
    High-level service for calling opencode agents.
    
    Manages session persistence per agent and message stacking
    for background models to handle network resilience.
    """

    def __init__(self, cli_client: CLIBridgeClient):
        self._client = cli_client
        self._sessions: dict[str, str] = config.get_agent_sessions()
        self._pending: dict[str, list[dict]] = config.get_pending_messages()
        self._bg_busy: dict[str, bool] = {agent: False for agent in ALL_BG_AGENTS}
        self._bg_reports: dict[str, str] = {}
        self._lock = threading.Lock()

    # ── Main Chat ──────────────────────────────────────────────────────────────

    def call_main_chat(
        self,
        user_message: str,
        topic_files: list[dict],
        prefs: dict,
        teacher_message: Optional[str] = None,
        on_result: Optional[Callable[[str], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ) -> None:
        """
        Call main chat agent.
        
        First turn: sends topic folder paths, question preferences, and message.
        Subsequent turns: sends teacher_message + student_message.
        
        Args:
            user_message: student's message
            topic_files: loaded topic dicts from library_scanner
            prefs: question preferences (section_a_sim, etc.) and question_count
            teacher_message: last AI response (None for first turn)
            on_result: callback with response text
            on_error: callback with error message
        """
        # Format message based on turn
        if teacher_message is None:
            # First turn: include topic context and preferences
            message = self._format_first_message(user_message, topic_files, prefs)
        else:
            # Subsequent turns
            message = f"Teacher message: {teacher_message}\nStudent message: {user_message}"
        
        session_id = self._sessions.get(AGENT_MAIN_CHAT)
        
        def _on_success(text: str, new_session_id: str) -> None:
            # Store session ID
            if new_session_id:
                self._sessions[AGENT_MAIN_CHAT] = new_session_id
                config.save_agent_session(AGENT_MAIN_CHAT, new_session_id)
            if on_result:
                on_result(text)
        
        self._client.call(
            agent=AGENT_MAIN_CHAT,
            session_id=session_id,
            user=message,
            on_success=_on_success,
            on_error=on_error,
        )

    def _format_first_message(
        self,
        user_message: str,
        topic_files: list[dict],
        prefs: dict,
    ) -> str:
        """
        Format first message with topic folder paths and preferences.
        
        The main chat agent will internally run topic-digest subagent.
        """
        # Topic paths
        topic_lines = []
        for tf in topic_files:
            topic_lines.append(f"- {tf['subject_name']}: {tf['topic_name']}")
        topics_text = "\n".join(topic_lines) if topic_lines else "No topics selected"
        
        # Question preferences
        prefs_lines = []
        if prefs.get('section_a_sim'):
            prefs_lines.append("Section A (Objective): Simulation")
        if prefs.get('section_a_nonsim'):
            prefs_lines.append("Section A (Objective): Non-Simulation")
        if prefs.get('section_b_sim'):
            prefs_lines.append("Section B (Theory): Simulation")
        if prefs.get('section_b_nonsim'):
            prefs_lines.append("Section B (Theory): Non-Simulation")
        prefs_text = "\n".join(prefs_lines) if prefs_lines else "No preferences set"
        
        # Question count
        question_count = prefs.get('question_count', 'Not specified')
        
        return (
            f"Topics to diagnose:\n{topics_text}\n\n"
            f"Question preferences:\n{prefs_text}\n\n"
            f"Number of questions: {question_count}\n\n"
            f"Student says: {user_message}"
        )

    # ── Background Models ──────────────────────────────────────────────────────

    def send_to_background_models(
        self,
        teacher_message: Optional[str],
        student_message: str,
        topic_digest: str = "",
    ) -> None:
        """
        Send message to all 4 background models.
        
        If a model is busy (still processing previous message),
        stack the message for later delivery.
        
        Args:
            teacher_message: last AI response (None for first turn)
            student_message: student's message
            topic_digest: concentrated topic digest from concept blocks
        """
        digest_section = f"\n\nTopic Context:\n{topic_digest}" if topic_digest else ""
        message = f"Teacher: {teacher_message}\nStudent: {student_message}{digest_section}"
        
        for agent in ALL_BG_AGENTS:
            with self._lock:
                if self._bg_busy[agent]:
                    # Stack the message
                    if agent not in self._pending:
                        self._pending[agent] = []
                    self._pending[agent].append({
                        'message': message,
                        'teacher': teacher_message,
                        'student': student_message,
                    })
                    config.save_pending_messages(agent, self._pending[agent])
                    continue
            
            # Send message
            self._send_to_background_model(agent, message)

    def _send_to_background_model(self, agent: str, message: str) -> None:
        """Send a single message to a background model."""
        with self._lock:
            self._bg_busy[agent] = True
        
        session_id = self._sessions.get(agent)
        
        def _on_success(text: str, new_session_id: str) -> None:
            # Store session ID
            if new_session_id:
                self._sessions[agent] = new_session_id
                config.save_agent_session(agent, new_session_id)
            
            # Store report
            with self._lock:
                self._bg_reports[agent] = text
                self._bg_busy[agent] = False
            
            # Process next pending message if any
            self._process_pending(agent)
        
        def _on_error(error: str) -> None:
            with self._lock:
                self._bg_busy[agent] = False
            
            # Stack the failed message for retry
            if agent not in self._pending:
                self._pending[agent] = []
            self._pending[agent].append({
                'message': message,
                'error': error,
            })
            config.save_pending_messages(agent, self._pending[agent])
        
        self._client.call(
            agent=agent,
            session_id=session_id,
            user=message,
            on_success=_on_success,
            on_error=_on_error,
        )

    def _process_pending(self, agent: str) -> None:
        """Process next pending message for an agent."""
        with self._lock:
            if agent in self._pending and self._pending[agent]:
                next_msg = self._pending[agent].pop(0)
                config.save_pending_messages(agent, self._pending[agent])
            else:
                return
        
        self._send_to_background_model(agent, next_msg['message'])

    # ── Quiz Generation ────────────────────────────────────────────────────────

    def call_quota_planner(
        self,
        background_reports: dict[str, str],
        user_request: str,
        total_questions: int,
        on_result: Optional[Callable[[dict], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ) -> None:
        """
        Call diagnostic-quota-planner agent.

        Passes all 4 background model reports + user request + question count.
        Agent 1 internally runs 3 subagents:
          1a: Priority Hierarchy Evaluator
          1b: Mathematical Quota Calculator
          1c: User Preference Adjuster
        Returns the parsed quota manifest JSON.

        Args:
            background_reports: {agent_name: report_text} from get_background_reports()
            user_request: the user's final chat message
            total_questions: number of questions requested
            on_result: callback with parsed manifest dict
            on_error: callback with error message
        """
        message = self._format_quota_input(
            background_reports, user_request, total_questions
        )

        session_id = self._sessions.get(AGENT_QUOTA_PLANNER)

        def _on_success(text: str, new_session_id: str) -> None:
            if new_session_id:
                self._sessions[AGENT_QUOTA_PLANNER] = new_session_id
                config.save_agent_session(AGENT_QUOTA_PLANNER, new_session_id)

            manifest = self._extract_json(text)
            if manifest is None:
                if on_error:
                    on_error(build_pipeline_error(
                        "Failed to parse the quota manifest from the agent's response.",
                        causes=[
                            "The 'diagnostic-quota-planner' agent is not registered in opencode.json.",
                            "The agent returned prose instead of JSON, or returned an empty response.",
                            "The opencode CLI failed (network, model, or configuration problem).",
                        ],
                    ))
                return

            errors = validate_quota_manifest(manifest)
            if errors:
                if on_error:
                    on_error(build_pipeline_error(
                        "The quota manifest failed validation.",
                        detail="; ".join(errors),
                    ))
                return

            config.save_quota_manifest(manifest)
            if on_result:
                on_result(manifest)

        def _on_error(error: str) -> None:
            if on_error:
                on_error(build_pipeline_error(
                    "The quota planner agent call failed.",
                    detail=error,
                    causes=[
                        "The 'diagnostic-quota-planner' agent is not registered in opencode.json.",
                        "The opencode CLI is not installed or not in PATH.",
                        "A network, rate-limit, or model configuration problem.",
                    ],
                ))

        self._client.call(
            agent=AGENT_QUOTA_PLANNER,
            session_id=session_id,
            user=message,
            on_success=_on_success,
            on_error=_on_error,
        )

    def _format_quota_input(
        self,
        reports: dict[str, str],
        user_request: str,
        total_questions: int,
    ) -> str:
        """Format the 4 background reports + user request for Agent 1."""
        bg_names = {
            'knowledge-graph-builder': 'Knowledge Graph Builder',
            'misconception-classifier': 'Misconception Classifier',
            'mechanism-evaluator': 'Mechanism Evaluator',
            'drill-recommender': 'Drill Recommender',
        }

        parts = [
            f"Total questions: {total_questions}",
            "",
        ]
        for agent_key, agent_label in bg_names.items():
            parts.append(f"=== {agent_label} REPORT ===")
            parts.append(reports.get(agent_key, 'No report'))
            parts.append("")

        parts.append("=== USER REQUEST ===")
        parts.append(user_request)

        return "\n".join(parts)

    # ── Agent 2: Query Specifier ─────────────────────────────────────────────

    def call_query_specifier(
        self,
        quota_manifest: dict,
        topic_files: list[dict],
        on_result: Optional[Callable[[dict], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ) -> None:
        """
        Runs the Agent 2 (metadata query specifier) pipeline.

        Sequence (updated approach — judgment AI, mechanical code):
            2a: call agent2a-topic-resolver  → resolved slot list
            2b: code tag mapping             → Type/Format assigned
            2c: call agent2c-fallback-builder → file query spec manifest
            2d: code validation + persist

        Each agent call is async, so the chain runs via nested callbacks.

        Args:
            quota_manifest: Agent 1 output (quiz_metadata + slot_allocations).
            topic_files:    in-memory loaded topic dicts (library_scanner).
            on_result:      callback with the validated file query spec manifest.
            on_error:       callback with a formatted pipeline error message.
        """
        def _report(msg: str) -> None:
            if on_error:
                on_error(msg)

        slots = quota_manifest.get('slot_allocations', [])
        index_text = self._build_bank_tag_index(topic_files)
        concept_text = self._build_concept_blocks_text(topic_files)

        # ── Step 3: fallback construction (2c) ───────────────────────────────
        def _on_2c_success(text: str, new_session_id: str) -> None:
            if new_session_id:
                self._sessions[AGENT_2C_FALLBACK_BUILDER] = new_session_id
                config.save_agent_session(AGENT_2C_FALLBACK_BUILDER, new_session_id)

            manifest = self._extract_json(text)
            if manifest is None:
                _report(build_pipeline_error(
                    "Failed to parse the file query spec manifest from the fallback-builder agent.",
                    causes=[
                        "The 'agent2c-fallback-builder' agent is not registered in opencode.json.",
                        "The agent returned prose instead of JSON, or returned an empty response.",
                        "The opencode CLI failed (network, model, or configuration problem).",
                    ],
                ))
                return

            errors = validate_query_spec_manifest(manifest)
            if errors:
                _report(build_pipeline_error(
                    "The file query spec manifest failed validation.",
                    detail="; ".join(errors),
                ))
                return

            config.save_query_spec_manifest(manifest)
            if on_result:
                on_result(manifest)

        def _on_2c_error(error: str) -> None:
            _report(build_pipeline_error(
                "The fallback-builder agent call failed.",
                detail=error,
                causes=[
                    "The 'agent2c-fallback-builder' agent is not registered in opencode.json.",
                    "The opencode CLI is not installed or not in PATH.",
                    "A network, rate-limit, or model configuration problem.",
                ],
            ))

        # ── Step 2b+2c: map tags, then call 2c ───────────────────────────────
        def _continue_after_2a(resolved_slots: list[dict]) -> None:
            # 2b: code tag mapping (join style_constraint from quota manifest)
            style_lookup = {
                slot.get('slot_number'): slot.get('style_constraint', '')
                for slot in slots if isinstance(slot, dict)
            }
            enriched = enrich_slots(resolved_slots, style_lookup)

            self._client.call(
                agent=AGENT_2C_FALLBACK_BUILDER,
                session_id=self._sessions.get(AGENT_2C_FALLBACK_BUILDER),
                user=self._format_2c_input(enriched, index_text),
                on_success=_on_2c_success,
                on_error=_on_2c_error,
            )

        # ── Step 1: topic resolution (2a) ────────────────────────────────────
        def _on_2a_success(text: str, new_session_id: str) -> None:
            if new_session_id:
                self._sessions[AGENT_2A_TOPIC_RESOLVER] = new_session_id
                config.save_agent_session(AGENT_2A_TOPIC_RESOLVER, new_session_id)

            resolved = self._extract_json(text)
            if resolved is None:
                _report(build_pipeline_error(
                    "Failed to parse the topic-resolution list from the topic-resolver agent.",
                    causes=[
                        "The 'agent2a-topic-resolver' agent is not registered in opencode.json.",
                        "The agent returned prose instead of JSON, or returned an empty response.",
                        "The opencode CLI failed (network, model, or configuration problem).",
                    ],
                ))
                return

            errors = validate_resolved_slots(resolved)
            if errors:
                _report(build_pipeline_error(
                    "The topic-resolution list failed validation.",
                    detail="; ".join(errors),
                ))
                return

            _continue_after_2a(resolved)

        def _on_2a_error(error: str) -> None:
            _report(build_pipeline_error(
                "The topic-resolver agent call failed.",
                detail=error,
                causes=[
                    "The 'agent2a-topic-resolver' agent is not registered in opencode.json.",
                    "The opencode CLI is not installed or not in PATH.",
                    "A network, rate-limit, or model configuration problem.",
                ],
            ))

        self._client.call(
            agent=AGENT_2A_TOPIC_RESOLVER,
            session_id=self._sessions.get(AGENT_2A_TOPIC_RESOLVER),
            user=self._format_2a_input(slots, concept_text, index_text),
            on_success=_on_2a_success,
            on_error=_on_2a_error,
        )

    def _format_2a_input(
        self,
        slots: list,
        concept_text: str,
        index_text: str,
    ) -> str:
        """Formats the step 2a prompt: quota slots + concept taxonomy + tag index."""
        return (
            "=== SLOT ALLOCATIONS ===\n"
            f"{json.dumps(slots, indent=2)}\n\n"
            "=== CONCEPT BLOCK TAXONOMY ===\n"
            f"{concept_text}\n\n"
            "=== BANK TAG INDEX ===\n"
            f"{index_text}\n\n"
            "Resolve each slot's topic to an actual bank topic name. "
            "Return ONLY the JSON array of resolved slots."
        )

    def _format_2c_input(
        self,
        enriched_slots: list[dict],
        index_text: str,
    ) -> str:
        """Formats the step 2c prompt: tag-resolved slots + bank tag index."""
        return (
            "=== RESOLVED SLOTS (tags assigned) ===\n"
            f"{json.dumps(enriched_slots, indent=2)}\n\n"
            "=== BANK TAG INDEX ===\n"
            f"{index_text}\n\n"
            "Construct the 3-tier fallback search spec for each slot. "
            "Return ONLY the JSON object with a 'file_query_specs' array."
        )

    # ── Agent 3: Candidate Evaluator ──────────────────────────────────────────

    def call_candidate_selector(
        self,
        quota_manifest: dict,
        candidate_pool: dict,
        background_reports: dict[str, str],
        on_result: Optional[Callable[[dict], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ) -> None:
        """
        Runs the Agent 3 (candidate evaluator) pipeline.

        Sequence (judgment AI, mechanical code):
            3a: code grouping            — already done by file_retriever
            3b: call agent3b-candidate-selector → semantic selections for
                slots with 2+ candidates
            3c: code fallback            — auto-select single-candidate slots,
                flag empty slots as MISSING
            3d: code assembly            — selected items manifest

        The agent call is async, so the chain runs via nested callbacks.
        Slots with 0 or 1 candidates never trigger an agent call (0 → flagged
        MISSING, 1 → auto-selected); 3b only judges ambiguous (2+) slots.

        Args:
            quota_manifest:    Agent 1 output (slot_allocations).
            candidate_pool:    {slot_number: [candidate_dict, ...]} from
                               file_retriever.retrieve_candidates().
            background_reports:{agent_name: report_text} diagnostic reports.
            on_result:         callback with the validated selected items manifest.
            on_error:          callback with a formatted pipeline error message.
        """
        def _report(msg: str) -> None:
            if on_error:
                on_error(msg)

        slots_by_number = self._slots_by_number(quota_manifest)
        missing: list[dict] = []
        auto:    dict[int, dict] = {}
        judge:   dict[int, list[dict]] = {}

        for slot_num, candidates in candidate_pool.items():
            if not isinstance(candidates, list) or not candidates:
                missing.append({
                    'slot_number': slot_num,
                    'reason': 'MISSING_BANK_ITEM',
                })
            elif len(candidates) == 1:
                auto[slot_num] = candidates[0]
            else:
                judge[slot_num] = candidates

        # ── Step 3d: assemble without an agent call if nothing needs judging ──
        def _assemble_and_finish(agent_selections: dict) -> None:
            manifest = self._assemble_selection_manifest(
                slots_by_number, auto, judge, agent_selections, missing
            )
            errors = validate_selected_items(manifest)
            if errors:
                _report(build_pipeline_error(
                    "The selected items manifest failed validation.",
                    detail="; ".join(errors),
                ))
                return

            config.save_selected_items(manifest)
            if on_result:
                on_result(manifest)

        if not judge:
            _assemble_and_finish({})
            return

        # ── Step 3b: semantic fit & distractor alignment (agent call) ─────────
        def _on_3b_success(text: str, new_session_id: str) -> None:
            if new_session_id:
                self._sessions[AGENT_3B_CANDIDATE_SELECTOR] = new_session_id
                config.save_agent_session(
                    AGENT_3B_CANDIDATE_SELECTOR, new_session_id
                )

            selections, err = self._parse_3b_selections(text, judge)
            if selections is None:
                _report(build_pipeline_error(
                    "Failed to parse the candidate selections from the "
                    "candidate-selector agent.",
                    detail=err or '',
                    causes=[
                        "The 'agent3b-candidate-selector' agent is not registered in opencode.json.",
                        "The agent returned prose instead of JSON, or returned an empty response.",
                        "The opencode CLI failed (network, model, or configuration problem).",
                    ],
                ))
                return

            _assemble_and_finish(selections)

        def _on_3b_error(error: str) -> None:
            _report(build_pipeline_error(
                "The candidate-selector agent call failed.",
                detail=error,
                causes=[
                    "The 'agent3b-candidate-selector' agent is not registered in opencode.json.",
                    "The opencode CLI is not installed or not in PATH.",
                    "A network, rate-limit, or model configuration problem.",
                ],
            ))

        self._client.call(
            agent=AGENT_3B_CANDIDATE_SELECTOR,
            session_id=self._sessions.get(AGENT_3B_CANDIDATE_SELECTOR),
            user=self._format_3b_input(
                slots_by_number, judge, background_reports
            ),
            on_success=_on_3b_success,
            on_error=_on_3b_error,
        )

    # ── Agent 4: Pedagogical Sequence Builder ────────────────────────────────

    def call_sequencer(
        self,
        selection_manifest: dict,
        background_reports: dict[str, str],
        on_result: Optional[Callable[[dict], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ) -> None:
        """
        Runs the Agent 4 (pedagogical sequence builder) pipeline.

        Sequence (judgment AI, mechanical code):
            4a: call agent4a-pacing-arc → choose the pacing arc (the only
                AI judgment step)
            4b: code — bucket selected items by objective type → pacing stage,
                sort within stage by match confidence
            4c: code — pick the Gateway (most approachable item) as position 1,
                keep same-topic / same-sim-set items consecutive
            4d: code — assign sequence_index / pacing_stage / position_rationale,
                validate, persist, hand the manifest to Agent 5

        The agent call is async, so the chain runs via nested callbacks.
        An empty selection manifest fails fast without an agent call.

        Args:
            selection_manifest:  Agent 3 output (selected_items).
            background_reports:  {agent_name: report_text} diagnostic reports.
            on_result:           callback with the validated sequenced quiz
                                 manifest.
            on_error:            callback with a formatted pipeline error message.
        """
        def _report(msg: str) -> None:
            if on_error:
                on_error(msg)

        items = selection_manifest.get('selected_items', [])
        if not items:
            _report(build_pipeline_error(
                "The sequencer received an empty selected-items list.",
                detail="No selected questions to sequence.",
                causes=[
                    "Agent 3 flagged every slot as MISSING.",
                    "The selected-items manifest is empty or corrupt.",
                ],
            ))
            return

        def _sequence_with_arc(arc: dict) -> None:
            manifest = sequencer.build_ordered_sequence(items, arc)
            errors = validate_sequenced_quiz(manifest)
            if errors:
                _report(build_pipeline_error(
                    "The sequenced quiz manifest failed validation.",
                    detail="; ".join(errors),
                ))
                return

            config.save_sequenced_quiz(manifest)
            if on_result:
                on_result(manifest)

        def _on_4a_success(text: str, new_session_id: str) -> None:
            if new_session_id:
                self._sessions[AGENT_4A_PACING_ARC] = new_session_id
                config.save_agent_session(
                    AGENT_4A_PACING_ARC, new_session_id
                )

            arc, err = self._parse_pacing_arc(text)
            if arc is None:
                _report(build_pipeline_error(
                    "Failed to parse the pacing arc from the sequencing agent.",
                    detail=err or '',
                    causes=[
                        "The 'agent4a-pacing-arc' agent is not registered in opencode.json.",
                        "The agent returned prose instead of JSON, or returned an empty response.",
                        "The opencode CLI failed (network, model, or configuration problem).",
                    ],
                ))
                return

            _sequence_with_arc(arc)

        def _on_4a_error(error: str) -> None:
            _report(build_pipeline_error(
                "The pacing-arc agent call failed.",
                detail=error,
                causes=[
                    "The 'agent4a-pacing-arc' agent is not registered in opencode.json.",
                    "The opencode CLI is not installed or not in PATH.",
                    "A network, rate-limit, or model configuration problem.",
                ],
            ))

        self._client.call(
            agent=AGENT_4A_PACING_ARC,
            session_id=self._sessions.get(AGENT_4A_PACING_ARC),
            user=self._format_4a_input(items, background_reports),
            on_success=_on_4a_success,
            on_error=_on_4a_error,
        )

    # ── Agent 4 helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _format_4a_input(
        items: list[dict],
        background_reports: dict[str, str],
    ) -> str:
        """Formats the step 4a prompt: selected-item profile + reports."""
        obj_counts: dict[str, int] = {}
        type_counts: dict[str, int] = {}
        for item in items:
            obj = item.get('objective_type', '')
            obj_counts[obj] = obj_counts.get(obj, 0) + 1
            q = item.get('selected_question', {})
            q_type = q.get('type', '')
            type_counts[q_type] = type_counts.get(q_type, 0) + 1

        profile = {
            'total_questions': len(items),
            'objective_type_counts': obj_counts,
            'question_type_counts': type_counts,
        }

        return (
            "=== SELECTED ITEM PROFILE ===\n"
            f"{json.dumps(profile, indent=2)}\n\n"
            "=== DIAGNOSTIC REPORTS ===\n"
            f"{AgentRunner._build_diagnostic_reports_text(background_reports)}\n\n"
            "Choose the pacing arc template that best fits this profile. "
            "Return ONLY the JSON object describing the arc."
        )

    def _parse_pacing_arc(self, text: str):
        """
        Parses and sanity-checks the raw 4a response.

        Returns (arc_dict, None) on success, or (None, error_detail) on
        failure. arc_dict = {pacing_strategy, target_cognitive_flow,
        stage_sequence, rationale}.
        """
        parsed = self._extract_json(text)
        if not isinstance(parsed, dict):
            return None, "Expected a JSON object describing the pacing arc."

        strategy = parsed.get('pacing_strategy')
        if not isinstance(strategy, str) or not strategy.strip():
            return None, "pacing_strategy must be a non-empty string."

        flow = parsed.get('target_cognitive_flow')
        if flow is not None and (not isinstance(flow, str)):
            return None, "target_cognitive_flow must be a string."

        stage_seq = parsed.get('stage_sequence')
        if stage_seq is not None and not isinstance(stage_seq, list):
            return None, "stage_sequence must be an array."

        errors: list[str] = []
        if isinstance(stage_seq, list):
            valid_stages = set(sequencer.DEFAULT_STAGE_ORDER)
            for i, entry in enumerate(stage_seq):
                label = f'stage_sequence[{i}]'
                if not isinstance(entry, dict):
                    errors.append(f'{label} must be an object')
                    continue
                stage = entry.get('stage')
                if not isinstance(stage, str) or stage not in valid_stages:
                    errors.append(
                        f'{label}.stage must be one of '
                        f'{sequencer.DEFAULT_STAGE_ORDER}'
                    )
                pr = entry.get('position_range')
                if pr is not None and (
                    not isinstance(pr, list)
                    or len(pr) != 2
                    or not all(isinstance(n, int) for n in pr)
                ):
                    errors.append(
                        f'{label}.position_range must be a [start, end] '
                        'integer pair'
                    )
        if errors:
            return None, '; '.join(errors)

        rationale = parsed.get('rationale')
        if rationale is not None and (
            not isinstance(rationale, str)
        ):
            return None, "rationale must be a string."

        return {
            'pacing_strategy': strategy,
            'target_cognitive_flow': flow or '',
            'stage_sequence': stage_seq or [],
            'rationale': rationale or '',
        }, None

    # ── Agent 5: Compliance Auditor ─────────────────────────────────────────

    def call_compliance_audit(
        self,
        sequence_manifest: dict,
        background_reports: dict[str, str],
        user_request: str,
        missing_items: list[dict] | None = None,
        on_result: Optional[Callable[[dict, dict], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ) -> None:
        """
        Runs the Agent 5 (compliance auditor) pipeline.

        Sequence (judgment AI, mechanical code):
            Step 1: code — structural & integrity audit (deterministic).
            Step 2: call agent5b-diagnostic-audit in parallel with
            Step 3: call agent5c-preference-audit (independent inputs).
            Step 4: code — decision gate (PASSED → sanitised payload;
                    FAILED → one targeted auto-retry of the AI audits, then
                    surface the failure + retry_instruction).

        Structural failures are not retryable by re-auditing (they indicate a
        pipeline bug) and surface immediately. Both AI audits run concurrently
        because CLIBridgeClient.call() spawns its own daemon thread.

        Args:
            sequence_manifest: Agent 4 output (ordered_quiz_sequence).
            background_reports:{agent_name: report_text} diagnostic reports.
            user_request:      the user's final chat message, verbatim.
            missing_items:     Agent 3's missing_items (audit notes a reduced
                               count; it is not a failure by itself).
            on_result:         (audit_result, production_payload) when PASSED.
            on_error:          formatted pipeline error when FAILED.
        """
        from . import compliance_auditor

        def _report(msg: str) -> None:
            if on_error:
                on_error(msg)

        def _quiz_summary() -> str:
            return self._format_5x_summary(sequence_manifest)

        structural = compliance_auditor.audit_structural(sequence_manifest)
        if not all(c.get('status') == 'PASS' for c in structural):
            result = compliance_auditor.assemble_audit_result(
                structural, None, None, missing_items
            )
            _report(build_pipeline_error(
                "The quiz failed the structural audit.",
                detail=result.get('retry_instruction', {}).get('action', ''),
                causes=[
                    "The sequenced manifest was produced by this app's own "
                    "deterministic sequencer — a structural failure indicates "
                    "a pipeline bug, not a user-data problem.",
                    "Check the sequencer output before retrying.",
                ],
            ))
            return

        def _finalise(diag: dict | None, pref: dict | None) -> None:
            result = compliance_auditor.assemble_audit_result(
                structural, diag, pref, missing_items
            )
            if result.get('audit_status') == 'PASSED':
                payload = compliance_auditor.build_production_payload(
                    sequence_manifest
                )
                config.save_compliance_audit(result)
                if on_result:
                    on_result(result, payload)
                return

            _report(build_pipeline_error(
                "The quiz failed the compliance audit.",
                detail=result.get('failure_reason', '') + ' — ' +
                       result.get('retry_instruction', {}).get('action', ''),
                causes=[
                    "The diagnostic alignment audit (5b) found critical "
                    "deficits without an addressing question.",
                    "The user-preference audit (5c) found the payload does "
                    "not match the user's explicit request.",
                    f"Target agent for rebuild: "
                    f"{result.get('retry_instruction', {}).get('target_agent')}",
                ],
            ))

        attempts = {'n': 0}

        def _run_parallel_audits() -> None:
            attempts['n'] += 1
            holder: dict = {}
            remaining = {'n': 2}

            def _done() -> None:
                remaining['n'] -= 1
                if remaining['n'] > 0:
                    return
                if attempts['n'] > 1:
                    # Second pass always surfaces (1 auto-retry used up).
                    _finalise(holder.get('diag'), holder.get('pref'))
                    return
                failed = (
                    (holder.get('diag') or {}).get('verdict') != 'PASS'
                    or (holder.get('pref') or {}).get('verdict') != 'PASS'
                )
                if failed:
                    # One automatic retry of the AI audits, then surface.
                    _run_parallel_audits()
                else:
                    _finalise(holder.get('diag'), holder.get('pref'))

            def _on_5b_success(text: str, new_session_id: str) -> None:
                if new_session_id:
                    self._sessions[AGENT_5B_DIAGNOSTIC_AUDIT] = new_session_id
                    config.save_agent_session(
                        AGENT_5B_DIAGNOSTIC_AUDIT, new_session_id
                    )
                verdict, err = self._parse_5b_verdict(text)
                if verdict is None:
                    _report(build_pipeline_error(
                        "Failed to parse the diagnostic audit verdict.",
                        detail=err or '',
                        causes=[
                            "The 'agent5b-diagnostic-audit' agent is not "
                            "registered in opencode.json.",
                            "The agent returned prose instead of JSON.",
                            "The opencode CLI failed (network/model problem).",
                        ],
                    ))
                    return
                holder['diag'] = verdict
                _done()

            def _on_5c_success(text: str, new_session_id: str) -> None:
                if new_session_id:
                    self._sessions[AGENT_5C_PREFERENCE_AUDIT] = new_session_id
                    config.save_agent_session(
                        AGENT_5C_PREFERENCE_AUDIT, new_session_id
                    )
                verdict, err = self._parse_5c_verdict(text)
                if verdict is None:
                    _report(build_pipeline_error(
                        "Failed to parse the preference audit verdict.",
                        detail=err or '',
                        causes=[
                            "The 'agent5c-preference-audit' agent is not "
                            "registered in opencode.json.",
                            "The agent returned prose instead of JSON.",
                            "The opencode CLI failed (network/model problem).",
                        ],
                    ))
                    return
                holder['pref'] = verdict
                _done()

            def _on_5b_error(error: str) -> None:
                _report(build_pipeline_error(
                    "The diagnostic-audit agent call failed.",
                    detail=error,
                    causes=[
                        "The 'agent5b-diagnostic-audit' agent is not "
                        "registered in opencode.json.",
                        "The opencode CLI is not installed or not in PATH.",
                        "A network, rate-limit, or model configuration problem.",
                    ],
                ))

            def _on_5c_error(error: str) -> None:
                _report(build_pipeline_error(
                    "The preference-audit agent call failed.",
                    detail=error,
                    causes=[
                        "The 'agent5c-preference-audit' agent is not "
                        "registered in opencode.json.",
                        "The opencode CLI is not installed or not in PATH.",
                        "A network, rate-limit, or model configuration problem.",
                    ],
                ))

            self._client.call(
                agent=AGENT_5B_DIAGNOSTIC_AUDIT,
                session_id=self._sessions.get(AGENT_5B_DIAGNOSTIC_AUDIT),
                user=self._format_5b_input(_quiz_summary(), background_reports),
                on_success=_on_5b_success,
                on_error=_on_5b_error,
            )
            self._client.call(
                agent=AGENT_5C_PREFERENCE_AUDIT,
                session_id=self._sessions.get(AGENT_5C_PREFERENCE_AUDIT),
                user=self._format_5c_input(_quiz_summary(), user_request),
                on_success=_on_5c_success,
                on_error=_on_5c_error,
            )

        _run_parallel_audits()

    # ── Agent 5 helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _format_5x_summary(sequence_manifest: dict) -> str:
        """Compact per-question summary for the 5b/5c prompts."""
        seq = sequence_manifest.get('ordered_quiz_sequence', [])
        summary = []
        for entry in seq:
            q = entry.get('question', {})
            summary.append({
                'sequence_index': entry.get('sequence_index', 0),
                'type': q.get('type', ''),
                'topic': q.get('topic', ''),
                'subject': q.get('subject', ''),
                'objective_type': entry.get('objective_type', ''),
                'pacing_stage': entry.get('pacing_stage', ''),
            })
        meta = sequence_manifest.get('sequence_metadata', {})
        return (
            "=== QUIZ SUMMARY ===\n"
            f"total_questions: {meta.get('total_questions')}\n"
            f"pacing_strategy: {meta.get('pacing_strategy')}\n\n"
            "=== QUIZ SEQUENCE ===\n"
            f"{json.dumps(summary, indent=2)}"
        )

    @staticmethod
    def _format_5b_input(
        quiz_summary: str,
        background_reports: dict[str, str],
    ) -> str:
        """Formats the step 5b prompt: quiz sequence + diagnostic reports."""
        return (
            f"{quiz_summary}\n\n"
            "=== DIAGNOSTIC REPORTS ===\n"
            f"{AgentRunner._build_diagnostic_reports_text(background_reports)}\n\n"
            "Verify the quiz covers the critical deficits in these reports. "
            "Return ONLY the JSON object with a 'verdict' and 'checks' array."
        )

    @staticmethod
    def _format_5c_input(
        quiz_summary: str,
        user_request: str,
    ) -> str:
        """Formats the step 5c prompt: quiz sequence + user request."""
        return (
            f"{quiz_summary}\n\n"
            "=== USER REQUEST (verbatim) ===\n"
            f"{user_request}\n\n"
            "Cross-check the quiz against this request. "
            "Return ONLY the JSON object with a 'verdict' and 'checks' array."
        )

    def _parse_5b_verdict(self, text: str):
        """Parses and sanity-checks the 5b response."""
        parsed = self._extract_json(text)
        if not isinstance(parsed, dict):
            return None, "Expected a JSON object with a 'verdict'."
        verdict = parsed.get('verdict')
        if verdict not in ('PASS', 'FAIL'):
            return None, "verdict must be 'PASS' or 'FAIL'."
        checks = parsed.get('checks')
        if not isinstance(checks, list):
            return None, "Missing 'checks' array."
        return {'verdict': verdict, 'checks': checks}, None

    def _parse_5c_verdict(self, text: str):
        """Parses and sanity-checks the 5c response."""
        parsed = self._extract_json(text)
        if not isinstance(parsed, dict):
            return None, "Expected a JSON object with a 'verdict'."
        verdict = parsed.get('verdict')
        if verdict not in ('PASS', 'FAIL'):
            return None, "verdict must be 'PASS' or 'FAIL'."
        checks = parsed.get('checks')
        if not isinstance(checks, list):
            return None, "Missing 'checks' array."
        return {'verdict': verdict, 'checks': checks}, None

    # ── Agent 3 helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _slots_by_number(quota_manifest: dict) -> dict[int, dict]:
        """Maps the quota manifest's slot_allocations to {slot_number: slot}."""
        result: dict[int, dict] = {}
        for slot in quota_manifest.get('slot_allocations', []):
            if isinstance(slot, dict) and isinstance(slot.get('slot_number'), int):
                result[slot['slot_number']] = slot
        return result

    def _format_3b_input(
        self,
        slots_by_number: dict[int, dict],
        judge: dict[int, list[dict]],
        background_reports: dict[str, str],
    ) -> str:
        """Formats the step 3b prompt: slots to judge + reports + candidates."""
        judge_slots = []
        for slot_num in sorted(judge):
            slot = slots_by_number.get(slot_num, {})
            judge_slots.append({
                'slot_number':     slot_num,
                'objective_type':  slot.get('objective_type', ''),
                'topic':           slot.get('topic', ''),
                'subject':         slot.get('subject', ''),
                'target_issue':    slot.get('target_issue', ''),
                'style_constraint': slot.get('style_constraint', ''),
                'desired_type':    judge[slot_num][0]['tags'].get('Type', ''),
            })

        return (
            "=== SLOT ALLOCATIONS (to judge) ===\n"
            f"{json.dumps(judge_slots, indent=2)}\n\n"
            "=== DIAGNOSTIC REPORTS ===\n"
            f"{self._build_diagnostic_reports_text(background_reports)}\n\n"
            "=== CANDIDATES ===\n"
            f"{self._build_candidates_text(judge)}\n\n"
            "Select the best candidate per slot. "
            "Return ONLY the JSON object with a 'selections' array."
        )

    @staticmethod
    def _build_candidates_text(judge: dict[int, list[dict]]) -> str:
        """Serialises the candidate pools for the slots 3b must judge."""
        parts: list[str] = []
        for slot_num in sorted(judge):
            parts.append(f"--- Slot {slot_num} ---")
            for idx, cand in enumerate(judge[slot_num]):
                parts.append(
                    f"candidate_index {idx} | type {cand['tags'].get('Type', '')} "
                    f"| format {cand['tags'].get('Format', '')} "
                    f"| tier {cand.get('tier', '')} "
                    f"| source {cand.get('source_topic', '')}"
                )
                parts.append("question_text:")
                parts.append(cand.get('question_text', ''))
                answer = cand.get('answer_text', '')
                if answer:
                    parts.append("answer_text: " + answer)
                parts.append("")
        return "\n".join(parts).strip()

    @staticmethod
    def _build_diagnostic_reports_text(reports: dict[str, str]) -> str:
        """Serialises the 4 background-model reports for the 3b prompt."""
        if not reports:
            return "No diagnostic reports available."
        labels = {
            'knowledge-graph-builder':   'Knowledge Graph Builder',
            'misconception-classifier':  'Misconception Classifier',
            'mechanism-evaluator':       'Mechanism Evaluator',
            'drill-recommender':         'Drill Recommender',
        }
        parts = []
        for agent_key, label in labels.items():
            parts.append(f"=== {label} REPORT ===")
            parts.append(reports.get(agent_key, 'No report'))
            parts.append("")
        return "\n".join(parts).strip()

    def _parse_3b_selections(
        self,
        text: str,
        judge: dict[int, list[dict]],
    ):
        """
        Parses and sanity-checks the raw 3b response.

        Returns (selections_dict, None) on success, or (None, error_detail)
        on failure. selections_dict is {slot_number: {candidate_index,
        match_confidence, selection_rationale}}.
        """
        parsed = self._extract_json(text)
        if not isinstance(parsed, dict):
            return None, "Expected a JSON object with a 'selections' array."
        raw = parsed.get('selections')
        if not isinstance(raw, list):
            return None, "Missing 'selections' array."

        selections: dict[int, dict] = {}
        errors: list[str] = []
        for i, sel in enumerate(raw):
            label = f'selections[{i}]'
            if not isinstance(sel, dict):
                errors.append(f'{label} must be an object')
                continue
            num = sel.get('slot_number')
            if not isinstance(num, int) or num not in judge:
                errors.append(
                    f'{label}.slot_number {num!r} is not a slot being judged'
                )
                continue
            idx = sel.get('candidate_index')
            if not isinstance(idx, int) or not (0 <= idx < len(judge[num])):
                errors.append(
                    f'{label}.candidate_index {idx!r} out of range for slot {num}'
                )
                continue
            selections[num] = {
                'slot_number':        num,
                'candidate_index':    idx,
                'match_confidence':   sel.get('match_confidence')
                                      or sel.get('confidence')
                                      or 'medium',
                'selection_rationale': sel.get('selection_rationale')
                                      or sel.get('rationale')
                                      or (
                                          f'Candidate {idx} selected by the '
                                          'candidate evaluator.'
                                      ),
            }

        judged = sorted(judge)
        omitted = [n for n in judged if n not in selections]
        if omitted:
            errors.append(
                'Missing selection for slot(s): ' + ', '.join(map(str, omitted))
            )

        if errors:
            return None, '; '.join(errors)
        return selections, None

    def _assemble_selection_manifest(
        self,
        slots_by_number: dict[int, dict],
        auto: dict[int, dict],
        judge: dict[int, list[dict]],
        agent_selections: dict[int, dict],
        missing: list[dict],
    ) -> dict:
        """
        Step 3d: builds the final selected items manifest.

        Auto-selected (single-candidate) and agent-selected (judged) slots
        become selected_items; empty slots become missing_items.
        """
        selected: list[dict] = []
        fallback_count = 0

        for slot_num, cand in auto.items():
            selected.append({
                'slot_number': slot_num,
                'selected_question': self._build_selected_question(cand),
                'objective_type': slots_by_number.get(slot_num, {}).get(
                    'objective_type', ''
                ),
                'source': 'bank',
            })
            if cand.get('tier') and cand['tier'] != 'tier_1_exact':
                fallback_count += 1

        for slot_num in sorted(judge):
            sel = agent_selections[slot_num]
            cand = judge[slot_num][sel['candidate_index']]
            item = {
                'slot_number': slot_num,
                'selected_question': self._build_selected_question(cand),
                'objective_type': slots_by_number.get(slot_num, {}).get(
                    'objective_type', ''
                ),
                'source': 'bank',
                'match_confidence': sel.get('match_confidence', 'medium'),
                'selection_rationale': sel.get('selection_rationale', ''),
            }
            if cand.get('tier') and cand['tier'] != 'tier_1_exact':
                fallback_count += 1
            selected.append(item)

        successful = len(selected)
        return {
            'selection_summary': {
                'total_slots': successful + len(missing),
                'successful_matches': successful,
                'fallback_used_count': fallback_count,
                'missing_count': len(missing),
            },
            'selected_items': selected,
            'missing_items': missing,
        }

    @staticmethod
    def _build_selected_question(cand: dict) -> dict:
        """
        Converts a candidate dict into the selected_question schema:
        MCQ candidates are split into stem + options; the bank answer text is
        carried as correct_answer.
        """
        q_type = cand['tags'].get('Type', '')
        full_text = cand.get('question_text', '')

        if q_type == 'MCQ':
            stem, options = split_mcq(full_text)
        else:
            stem, options = full_text, []

        return {
            'text': stem,
            'type': q_type,
            'subject': cand.get('source_subject', cand['tags'].get('Subject', '')),
            'topic': cand.get('source_topic', cand['tags'].get('Topic', '')),
            'format': cand['tags'].get('Format', 'Non-Sim'),
            'options': options,
            'correct_answer': cand.get('answer_text', ''),
        }

    @staticmethod
    def _build_bank_tag_index(topic_files: list[dict]) -> str:
        """
        Summarises the subjects, topics, Types, and Formats available in the
        loaded banks, for the 2a and 2c prompts to constrain their output.
        """
        from .file_retriever import build_tag_index

        index = build_tag_index(topic_files)
        if not index:
            return "No tagged questions found in the loaded banks."

        subjects: dict[str, set] = {}
        types: set[str] = set()
        formats: set[str] = set()
        for e in index:
            subjects.setdefault(e['subject'], set()).add(e['topic'])
            if e['type']:
                types.add(e['type'])
            if e['format']:
                formats.add(e['format'])

        lines = []
        for subject in sorted(subjects):
            topics = ", ".join(sorted(subjects[subject]))
            lines.append(f"- Subject: {subject}")
            lines.append(f"    Topics: {topics}")
        lines.append(f"Types: {', '.join(sorted(types)) or 'none tagged'}")
        lines.append(f"Formats: {', '.join(sorted(formats)) or 'none tagged'}")
        return "\n".join(lines)

    @staticmethod
    def _build_concept_blocks_text(topic_files: list[dict]) -> str:
        """
        Concatenates the raw concept_block JSON for all loaded topics, so 2a
        can resolve prerequisite links (e.g. Quadratic Equations →
        Factoring Polynomials).
        """
        blocks = []
        for tf in topic_files:
            raw = tf.get('concept_block', '')
            if raw and raw.strip():
                blocks.append(raw.strip())
        return "\n\n".join(blocks) if blocks else "No concept blocks available."

    def _extract_json(self, text: str):
        """Extract JSON from agent response text. Tries parsing full text first,
        then searches for JSON between code fences or braces. Returns a dict,
        list, or None if no parseable JSON is found."""
        text = text.strip()

        # Try direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try between ```json ... ```
        import re
        m = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1).strip())
            except json.JSONDecodeError:
                pass

        # Find first { ... } block
        brace_start = text.find('{')
        brace_end = text.rfind('}')
        if brace_start != -1 and brace_end > brace_start:
            try:
                return json.loads(text[brace_start:brace_end + 1])
            except json.JSONDecodeError:
                pass

        # Find first [ ... ] block
        bracket_start = text.find('[')
        bracket_end = text.rfind(']')
        if bracket_start != -1 and bracket_end > bracket_start:
            try:
                return json.loads(text[bracket_start:bracket_end + 1])
            except json.JSONDecodeError:
                pass

        return None

    def resolve_pending_and_get_reports(
        self,
        on_complete: Optional[Callable[[dict], None]] = None,
    ) -> None:
        """
        Resolve all outstanding stacks and get final reports.
        
        Called when user clicks "Generate Quiz". Waits for all
        pending messages to complete, then returns final reports.
        
        Args:
            on_complete: callback with {agent_name: report_text}
        """
        def _wait_and_return():
            # Wait for all background models to finish
            while True:
                with self._lock:
                    all_idle = not any(self._bg_busy.values())
                    has_pending = any(
                        agent in self._pending and self._pending[agent]
                        for agent in ALL_BG_AGENTS
                    )
                
                if all_idle and not has_pending:
                    break
                
                # Small sleep to avoid busy waiting
                import time
                time.sleep(0.1)
            
            # Return final reports
            if on_complete:
                on_complete(dict(self._bg_reports))
        
        threading.Thread(target=_wait_and_return, daemon=True, name='resolve-reports').start()

    def get_background_reports(self) -> dict[str, str]:
        """Returns current background model reports (non-blocking)."""
        return dict(self._bg_reports)

    # ── Session Management ─────────────────────────────────────────────────────

    def clear_sessions(self) -> None:
        """Clear all agent sessions (new quiz session)."""
        self._sessions.clear()
        self._pending.clear()
        self._bg_reports.clear()
        with self._lock:
            self._bg_busy = {agent: False for agent in ALL_BG_AGENTS}
        config.clear_agent_sessions()
        config.clear_pending_messages()
