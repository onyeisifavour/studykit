"""
quiz_page.py

The Quiz page runs a state machine:

    CHAT  -> THINK -> LOAD -> QUIZ -> DONE

  CHAT:  student and AI discuss topics/count/weak areas (chat_view.py),
         plus a per-quiz "if I skip a question" scoring toggle.
  THINK: one API call generates the hidden blueprint (blueprint_generator.py),
         then question-type filters (Settings) are hard-enforced in code —
         see blueprint_generator.apply_type_filters().
  LOAD:  one or two API calls select/generate the actual questions
         (question_generator.py + answer_matcher.py).
  QUIZ:  questions shown one at a time; MCQ marked locally, SUBJ evaluated
         live (if evaluation ON) or stored for batch scoring (if OFF).
         Skip is always available, independent of Submit.
  DONE:  blank/skipped answers are scored 0 locally and NEVER sent to the
         AI (this is what previously caused hallucinated positive feedback
         on a quiz the student hadn't actually answered), then any
         remaining SUBJ answers are batch-scored, then the summary report
         is requested.

BACK vs CANCEL during THINK/LOAD:
  - Back: lets the student peek at the Chat screen to reread the
    conversation WITHOUT touching the in-flight API call — it keeps
    running in the background. A banner in the chat view reflects
    progress; tapping "Continue" resumes wherever the pipeline actually is
    (still loading, or ready).
  - Cancel: invalidates the in-flight request via a generation-token
    counter (its eventual callback becomes a no-op) and drops into a
    Retry screen for that same stage.

  This needs "what stage the pipeline is really in" (self._pipeline_stage)
  decoupled from "what's currently rendered" (self._view) — see
  _set_view() / _peek_at_chat() / _resume_from_peek().
"""

import re
import subprocess
import webbrowser
from pathlib import Path
from typing import Optional

import tkinter as tk

from .theme import C, FONT_BODY, FONT_LABEL, FONT_H2, FONT_H3, Page
from .chat_view import ChatView
from .. import config
from .. import library_scanner
from .. import quiz_logger
from .. import blueprint_generator
from .. import question_generator
from .. import answer_matcher
from .. import simulation_reader
from .. import prompts
from .. import file_retriever
from .. import compliance_auditor
from ..manifest_validator import validate_candidate_pool
from ..session_log import SessionLog


class QuizPage(Page):

    def __init__(self, parent, root, api_client, evaluation_runner, agent_runner=None, on_navigate=None):
        super().__init__(parent)
        self._root        = root
        self._api         = api_client
        self._runner      = evaluation_runner
        self._agent_runner = agent_runner
        self._on_navigate = on_navigate

        self._pipeline_stage = 'idle'   # idle -> chat -> think -> load -> quiz -> done
        self._view = 'normal'            # 'normal' | 'chat_peek'
        self._current_render_fn = None   # what the 'normal' view should show right now
        self._peek_status_text  = ""
        self._gen_token = 0

        self._topic_files: list[dict] = []
        self._chat_view: Optional[ChatView] = None
        self._blueprint = None
        self._quota_manifest: dict = {}
        self._candidate_pool: dict = {}
        self._selected_items: dict = {}
        self._sequenced_quiz: dict = {}
        self._compliance_audit: dict = {}
        self._answer_matches: list[dict] = []
        self._questions: list = []
        self._current_idx = 0
        self._quiz_log = None
        self._session_log = SessionLog()
        self._evaluation_on = True
        self._current_skip_mode = 'zero'

        self._mcq_var = None
        self._answer_text = None

        self._build_shell()

    # ── Shell (persists across states) ────────────────────────────────────────
    def _build_shell(self):
        header = tk.Frame(self, bg=C["content_bg"])
        header.pack(fill="x", padx=36, pady=(30, 0))

        tk.Label(header, text="Quiz", font=FONT_H2,
                 bg=C["content_bg"], fg=C["text_primary"]).pack(side="left")

        self._stage_lbl = tk.Label(header, text="", font=("Segoe UI", 10, "bold"),
                                    bg=C["accent_blue"], fg="white", padx=10, pady=4)
        self._stage_lbl.pack(side="right")

        tk.Frame(self, bg=C["border"], height=1).pack(fill="x", padx=36, pady=16)

        self._body = tk.Frame(self, bg=C["content_bg"])
        self._body.pack(fill="both", expand=True, padx=36, pady=(0, 30))

    def on_show(self):
        if self._pipeline_stage == 'idle':
            self._start_new_session()

    def _clear_body(self):
        for w in self._body.winfo_children():
            w.destroy()

    def _render_loading(self, message: str):
        tk.Label(self._body, text=message, font=FONT_H3,
                 bg=C["content_bg"], fg=C["text_secondary"]).pack(anchor="w", pady=(60, 0))

    # ── View/peek decoupling ──────────────────────────────────────────────────
    def _set_view(self, render_fn, peek_status_text: str = ""):
        """
        Registers `render_fn` as what the 'normal' view should currently
        show, and — unless the student is peeking at Chat — renders it
        immediately. If they ARE peeking, the render is deferred and only
        the peek banner's status text updates, so progress is visible
        without yanking them away from what they're reading.
        """
        self._current_render_fn = render_fn
        self._peek_status_text = peek_status_text
        if self._view == 'chat_peek':
            if hasattr(self, '_peek_banner_lbl') and self._peek_banner_lbl.winfo_exists():
                self._peek_banner_lbl.config(text=peek_status_text)
            return
        self._clear_body()
        render_fn()

    def _render_loading_with_controls(self, message: str):
        tk.Label(self._body, text=message, font=FONT_H3,
                 bg=C["content_bg"], fg=C["text_secondary"]).pack(anchor="w", pady=(60, 20))

        ctrl = tk.Frame(self._body, bg=C["content_bg"])
        ctrl.pack(anchor="w")

        back_btn = tk.Label(ctrl, text="← Back to Chat", font=("Segoe UI", 9, "bold"),
                             bg=C["text_secondary"], fg="white", padx=14, pady=7, cursor="hand2")
        back_btn.pack(side="left")
        back_btn.bind("<Button-1>", lambda _: self._peek_at_chat())

        cancel_btn = tk.Label(ctrl, text="✕ Cancel", font=("Segoe UI", 9, "bold"),
                               bg=C["incorrect"], fg="white", padx=14, pady=7, cursor="hand2")
        cancel_btn.pack(side="left", padx=(8, 0))
        cancel_btn.bind("<Button-1>", lambda _: self._cancel_current_stage())

    # ── Peek-at-chat (Back button) ───────────────────────────────────────────
    def _peek_at_chat(self):
        self._view = 'chat_peek'
        self._clear_body()

        if self._chat_view:
            self._chat_view.pack(fill="both", expand=True)

        banner = tk.Frame(self._body, bg=C["card_bg"],
                           highlightbackground=C["border"], highlightthickness=1)
        banner.pack(fill="x", side="bottom", pady=(10, 0))

        self._peek_banner_lbl = tk.Label(
            banner, text=self._peek_status_text or "Still working…", font=FONT_LABEL,
            bg=C["card_bg"], fg=C["text_secondary"], padx=14, pady=8,
        )
        self._peek_banner_lbl.pack(side="left")

        continue_btn = tk.Label(banner, text="Continue →", font=("Segoe UI", 9, "bold"),
                                 bg=C["accent_blue"], fg="white", padx=12, pady=6, cursor="hand2")
        continue_btn.pack(side="right", padx=10, pady=6)
        continue_btn.bind("<Button-1>", lambda _: self._resume_from_peek())

    def _resume_from_peek(self):
        self._view = 'normal'
        self._clear_body()
        if self._current_render_fn:
            self._current_render_fn()

    # ── Cancel / retry ────────────────────────────────────────────────────────
    def _cancel_current_stage(self):
        self._gen_token += 1   # invalidates any in-flight callback for this stage
        cancelled_stage = self._pipeline_stage
        self._view = 'normal'
        self._clear_body()
        self._render_cancelled_screen(cancelled_stage)

    def _render_cancelled_screen(self, stage: str):
        tk.Label(self._body, text="Cancelled.", font=FONT_H3,
                 bg=C["content_bg"], fg=C["text_primary"]).pack(anchor="w", pady=(40, 6))
        tk.Label(self._body, text="The request was abandoned. You can try that step again.",
                 font=FONT_BODY, bg=C["content_bg"], fg=C["text_secondary"]).pack(anchor="w")

        retry_btn = tk.Label(self._body, text="Retry →", font=("Segoe UI", 10, "bold"),
                              bg=C["accent_blue"], fg="white", padx=16, pady=8, cursor="hand2")
        retry_btn.pack(anchor="w", pady=(16, 0))
        retry_btn.bind("<Button-1>", lambda _: self._retry_stage(stage))

        back_btn = tk.Label(self._body, text="← Back to Chat instead", font=("Segoe UI", 9, "bold"),
                             bg=C["text_secondary"], fg="white", padx=14, pady=7, cursor="hand2")
        back_btn.pack(anchor="w", pady=(10, 0))
        back_btn.bind("<Button-1>", lambda _: self._enter_chat_state())

    def _retry_stage(self, stage: str):
        if stage == 'think':
            self._enter_think_state()
        elif stage == 'load':
            self._enter_load_state()
        else:
            self._enter_chat_state()

    # ── Session bootstrap ──────────────────────────────────────────────────────
    def _start_new_session(self):
        selected = config.get_selected_topics()
        if not selected:
            self._render_no_topics_warning()
            return

        self._topic_files = library_scanner.load_selected_topics(selected)
        if not self._topic_files:
            self._render_no_topics_warning()
            return

        # Clear agent sessions for new quiz
        if self._agent_runner:
            self._agent_runner.clear_sessions()

        self._evaluation_on = config.get_evaluation_on()
        self._current_skip_mode = config.get_last_skip_mode()
        self._enter_chat_state()

    def _render_no_topics_warning(self):
        self._pipeline_stage = 'idle'
        self._clear_body()
        self._stage_lbl.config(text="SETUP NEEDED", bg=C["incorrect"])

        tk.Label(self._body, text="No topics selected yet.", font=FONT_H3,
                 bg=C["content_bg"], fg=C["text_primary"]).pack(anchor="w", pady=(20, 6))
        tk.Label(self._body,
                 text="Go to Settings, scan your learning library, and select "
                      "at least one topic before starting a quiz.",
                 font=FONT_BODY, bg=C["content_bg"], fg=C["text_secondary"],
                 wraplength=480, justify="left").pack(anchor="w")

        if self._on_navigate:
            btn = tk.Label(self._body, text="Open Settings →", font=("Segoe UI", 10, "bold"),
                            bg=C["accent_blue"], fg="white", padx=16, pady=8, cursor="hand2")
            btn.pack(anchor="w", pady=(16, 0))
            btn.bind("<Button-1>", lambda _: self._on_navigate("settings"))

    # ── CHAT state ──────────────────────────────────────────────────────────────
    def _enter_chat_state(self):
        self._pipeline_stage = 'chat'
        self._view = 'normal'
        self._stage_lbl.config(text="CHAT", bg=C["accent_blue"])
        self._clear_body()

        skip_row = tk.Frame(self._body, bg=C["content_bg"])
        skip_row.pack(fill="x", pady=(0, 10))
        tk.Label(skip_row, text="If I skip a question:", font=FONT_LABEL,
                 bg=C["content_bg"], fg=C["text_secondary"]).pack(side="left")

        self._skip_zero_btn = tk.Label(skip_row, text="Count as 0", font=("Segoe UI", 9, "bold"),
                                        padx=10, pady=4, cursor="hand2")
        self._skip_zero_btn.pack(side="left", padx=(8, 4))
        self._skip_zero_btn.bind("<Button-1>", lambda _: self._set_skip_mode('zero'))

        self._skip_exclude_btn = tk.Label(skip_row, text="Exclude from score", font=("Segoe UI", 9, "bold"),
                                           padx=10, pady=4, cursor="hand2")
        self._skip_exclude_btn.pack(side="left")
        self._skip_exclude_btn.bind("<Button-1>", lambda _: self._set_skip_mode('exclude'))

        self._apply_skip_mode_styling()

        # Get preferences for main chat
        prefs = config.get_question_section_preferences()
        prefs['question_count'] = config.get_question_count()

        self._chat_view = ChatView(
            self._body, self._root, self._agent_runner, self._topic_files, prefs,
            on_ready_to_generate=self._enter_think_state,
        )
        self._chat_view.pack(fill="both", expand=True)

    def _set_skip_mode(self, mode: str):
        self._current_skip_mode = mode
        config.save_last_skip_mode(mode)
        self._apply_skip_mode_styling()

    def _apply_skip_mode_styling(self):
        is_zero = self._current_skip_mode == 'zero'
        self._skip_zero_btn.config(bg=C["accent_blue"] if is_zero else C["text_secondary"], fg="white")
        self._skip_exclude_btn.config(bg=C["accent_blue"] if not is_zero else C["text_secondary"], fg="white")

    # ── THINK state (blueprint generation) ───────────────────────────────────────
    def _enter_think_state(self):
        self._pipeline_stage = 'think'
        self._gen_token += 1
        my_token = self._gen_token
        self._stage_lbl.config(text="PLANNING", bg=C["accent"])
        self._set_view(lambda: self._render_loading_with_controls("Designing your quiz blueprint…"),
                        "Still designing your quiz blueprint…")

        # Agent-based path: call Agent 1 (quota planner) first
        if self._agent_runner:
            reports = self._agent_runner.get_background_reports()
            history = self._chat_view.get_history() if self._chat_view else []
            user_request = history[-1]['content'] if history else "Generate quiz"
            total_questions = config.get('question_count', 10)

            self._agent_runner.call_quota_planner(
                background_reports=reports,
                user_request=user_request,
                total_questions=total_questions,
                on_result=lambda manifest: self._root.after(
                    0, lambda: self._on_quota_manifest_ready(my_token, manifest)
                ),
                on_error=lambda err: self._root.after(
                    0, lambda: self._on_pipeline_error(my_token, 'quota planning', err)
                ),
            )
            return

        # Legacy path: prompt-based blueprint generation
        self._legacy_generate_blueprint(my_token)

    def _on_quota_manifest_ready(self, token: int, manifest: dict):
        """Agent 1 returned quota manifest. Store and proceed to Agent 2."""
        if token != self._gen_token:
            return

        # Store manifest for downstream agents (Agent 2-5, Sim S1-S3)
        config.save_quota_manifest(manifest)
        self._quota_manifest = manifest

        if not self._agent_runner:
            # Defensive: this callback only fires on the agent path, but fall
            # through gracefully if the runner was torn down meanwhile.
            self._legacy_generate_blueprint(token)
            return

        # Run Agent 2 (metadata query specifier): 2a → tag mapping → 2c
        self._agent_runner.call_query_specifier(
            quota_manifest=manifest,
            topic_files=self._topic_files,
            on_result=lambda spec: self._root.after(
                0, lambda: self._on_query_spec_ready(token, spec)
            ),
            on_error=lambda err: self._root.after(
                0, lambda: self._on_pipeline_error(token, 'query specification', err)
            ),
        )

    def _on_query_spec_ready(self, token: int, spec_manifest: dict):
        """
        Agent 2 returned the file query spec manifest. Run the file retriever
        (code), validate the candidate pool, then hand it to Agent 3 (candidate
        selector).
        """
        if token != self._gen_token:
            return

        pool = file_retriever.retrieve_candidates(spec_manifest, self._topic_files)
        errors = validate_candidate_pool(pool)
        if errors:
            self._on_pipeline_error(
                token, 'query specification',
                "The candidate pool failed validation.\n\n" + "; ".join(errors),
            )
            return

        # In-memory only (Issue #8) — not written to config.json
        self._candidate_pool = pool

        if not self._agent_runner:
            # Defensive: the agent path built this pool, but fall through
            # gracefully if the runner was torn down meanwhile.
            self._legacy_generate_blueprint(token)
            return

        # Run Agent 3 (candidate evaluator): 3a grouping → 3b selection →
        # 3c fallback → 3d selected items manifest
        self._agent_runner.call_candidate_selector(
            quota_manifest=self._quota_manifest,
            candidate_pool=pool,
            background_reports=self._agent_runner.get_background_reports(),
            on_result=lambda sel: self._root.after(
                0, lambda: self._on_selection_ready(token, sel)
            ),
            on_error=lambda err: self._root.after(
                0, lambda: self._on_pipeline_error(token, 'candidate selection', err)
            ),
        )

    def _on_selection_ready(self, token: int, selection_manifest: dict):
        """
        Agent 3 returned the selected items manifest. Store it in-memory for
        downstream agents (Agent 4+). Runs Agent 4 (sequencer) on it; the
        legacy blueprint flow remains as a fallback when the agent runner is
        unavailable.
        """
        if token != self._gen_token:
            return

        # In-memory only — not written to config.json (Issue #8 pattern)
        self._selected_items = selection_manifest

        if not self._agent_runner:
            self._legacy_generate_blueprint(token)
            return

        self._pipeline_stage = 'sequence'
        self._stage_lbl.config(text="SEQUENCING", bg=C["accent"])
        self._set_view(
            lambda: self._render_loading_with_controls("Sequencing your questions…"),
            "Still sequencing your questions…",
        )
        self._agent_runner.call_sequencer(
            selection_manifest=selection_manifest,
            background_reports=self._agent_runner.get_background_reports(),
            on_result=lambda seq: self._root.after(
                0, lambda: self._on_sequenced_ready(token, seq)
            ),
            on_error=lambda err: self._root.after(
                0, lambda: self._on_pipeline_error(token, 'sequencing', err)
            ),
        )

    def _on_sequenced_ready(self, token: int, sequence_manifest: dict):
        """
        Agent 4 returned the sequenced quiz manifest. Run Agent 5 (compliance
        audit) on it; the sanitised payload feeds the quiz. Falls back to
        building directly when the agent runner is unavailable.
        """
        if token != self._gen_token:
            return

        self._sequenced_quiz = sequence_manifest

        if not self._agent_runner:
            self._start_quiz_from_sequence(sequence_manifest)
            return

        history = self._chat_view.get_history() if self._chat_view else []
        user_request = history[-1]['content'] if history else "Generate quiz"

        self._pipeline_stage = 'audit'
        self._stage_lbl.config(text="AUDITING", bg=C["accent"])
        self._set_view(
            lambda: self._render_loading_with_controls("Auditing your quiz…"),
            "Still auditing your quiz…",
        )
        self._agent_runner.call_compliance_audit(
            sequence_manifest=sequence_manifest,
            background_reports=self._agent_runner.get_background_reports(),
            user_request=user_request,
            missing_items=self._selected_items.get('missing_items', []),
            on_result=lambda result, payload: self._root.after(
                0, lambda: self._on_audit_ready(token, result, payload)
            ),
            on_error=lambda err: self._root.after(
                0, lambda: self._on_pipeline_error(token, 'compliance audit', err)
            ),
        )

    def _on_audit_ready(self, token: int, audit_result: dict, payload: dict):
        """
        Agent 5 returned the audit verdict. On PASSED, rebuild the question
        list from the sanitised payload and start the quiz. FAILED never
        reaches here — call_compliance_audit surfaces it via on_error after
        the one auto-retry.
        """
        if token != self._gen_token:
            return

        self._compliance_audit = audit_result
        manifest = compliance_auditor.rebuild_sequence_manifest(payload)
        self._start_quiz_from_sequence(manifest)

    def _start_quiz_from_sequence(self, sequence_manifest: dict):
        """
        Shared sequence→quiz block: builds questions from a sequenced manifest
        (no re-sort), applies the shuffle preference, and starts the quiz.
        Used by both the Agent 4 path and the Agent 5 payload path.
        """
        questions = question_generator.build_questions_from_sequence(sequence_manifest)
        questions = [q for q in questions if q.question_text.strip()]

        if not questions:
            self._set_view(
                lambda: self._render_stage_error(
                    'sequencing',
                    "No usable questions were produced. Please try again.",
                ),
                "⚠ Sequencing problem — tap Continue to see details",
            )
            return

        # Apply shuffle preference (default: no shuffling)
        shuffle_prefs = config.get_shuffle_preferences()
        if shuffle_prefs['shuffle_enabled']:
            questions = question_generator.shuffle_questions(
                questions, shuffle_prefs['keep_sim_together']
            )

        self._start_quiz_with_questions(questions)

    def _legacy_generate_blueprint(self, token: int):
        """Legacy prompt-based blueprint generation (will be replaced)."""
        if token != self._gen_token:
            return

        history = self._chat_view.get_history() if self._chat_view else []
        concept_blocks = prompts.build_multi_topic_concepts(self._topic_files)
        sim_readmes = simulation_reader.build_sim_context_block(
            simulation_reader.collect_sim_readmes(self._topic_files)
        )
        question_banks = prompts.build_multi_topic_banks(self._topic_files)

        prefs = config.get_question_section_preferences()
        type_note = prompts.build_section_constraint_note(
            prefs['section_a_sim'], prefs['section_a_nonsim'],
            prefs['section_b_sim'], prefs['section_b_nonsim']
        )

        user_prompt = prompts.build_blueprint_prompt(
            history, concept_blocks, sim_readmes, question_banks, type_note
        )

        self._api.call(
            system=prompts.BLUEPRINT_SYSTEM,
            user=user_prompt,
            on_success=lambda r: self._root.after(0, lambda: self._on_blueprint_ready(token, r)),
            on_error=lambda e: self._root.after(0, lambda: self._on_pipeline_error(token, 'blueprint generation', e)),
            max_tokens=2500,
        )

    def _on_blueprint_ready(self, token: int, raw_text: str):
        if token != self._gen_token:
            return   # cancelled — ignore this stale result

        self._blueprint = blueprint_generator.parse_blueprint(raw_text)

        prefs = config.get_question_section_preferences()
        self._blueprint = blueprint_generator.apply_section_filters(
            self._blueprint, prefs['section_a_sim'], prefs['section_a_nonsim'],
            prefs['section_b_sim'], prefs['section_b_nonsim']
        )

        if self._blueprint.total == 0:
            self._set_view(
                lambda: self._render_stage_error(
                    'blueprint generation',
                    "No usable questions remained after applying your Settings' "
                    "question-type filters. Try enabling another type, or ask "
                    "for more questions in Chat.",
                ),
                "⚠ Blueprint problem — tap Continue to see details",
            )
            return

        self._enter_load_state()

    def _on_pipeline_error(self, token: int, stage: str, error_msg: str):
        if token != self._gen_token:
            return
        self._set_view(
            lambda: self._render_stage_error(stage, error_msg),
            f"⚠ {stage} failed — tap Continue to see details",
        )

    # ── LOAD state (question generation) ─────────────────────────────────────────
    def _enter_load_state(self):
        self._pipeline_stage = 'load'
        self._gen_token += 1
        my_token = self._gen_token
        self._stage_lbl.config(text="GENERATING", bg=C["accent"])
        self._set_view(
            lambda: self._render_loading_with_controls(f"Selecting {self._blueprint.total} questions…"),
            "Still selecting your questions…",
        )

        question_banks = prompts.build_multi_topic_banks(self._topic_files)
        user_prompt = prompts.build_non_sim_prompt(self._blueprint.raw_text, question_banks)

        self._api.call(
            system=prompts.NON_SIM_QUESTIONS_SYSTEM,
            user=user_prompt,
            on_success=lambda r: self._root.after(0, lambda: self._on_non_sim_ready(my_token, r)),
            on_error=lambda e: self._root.after(0, lambda: self._on_load_error(my_token, 'question selection', e)),
            max_tokens=3000,
        )

    def _on_non_sim_ready(self, token: int, raw_text: str):
        if token != self._gen_token:
            return

        pairs = question_generator.parse_non_sim_questions(raw_text)
        pair_map = {code.upper(): text for code, text in pairs}

        aligned: list[str] = []
        for entry in self._blueprint.entries:
            if entry.is_simulation:
                aligned.append('[EMPTY]')
            else:
                aligned.append(pair_map.get(entry.q_code, ''))

        self._answer_matches = answer_matcher.match_all_questions(aligned, self._topic_files)

        if self._blueprint.has_simulations():
            self._set_view(
                lambda: self._render_loading_with_controls("Preparing simulation questions…"),
                "Still preparing simulation questions…",
            )
            sim_readmes = simulation_reader.build_sim_context_block(
                simulation_reader.collect_sim_readmes(self._topic_files)
            )
            user_prompt = prompts.build_sim_prompt(self._blueprint.raw_text, sim_readmes)

            self._api.call(
                system=prompts.SIM_QUESTIONS_SYSTEM,
                user=user_prompt,
                on_success=lambda r: self._root.after(0, lambda: self._on_sim_ready(token, r)),
                on_error=lambda e: self._root.after(0, lambda: self._on_load_error(token, 'simulation question generation', e)),
                max_tokens=3000,
            )
        else:
            self._finalise_questions(token, [])

    def _on_sim_ready(self, token: int, raw_text: str):
        if token != self._gen_token:
            return
        sim_sets = question_generator.parse_sim_sets(raw_text)
        self._finalise_questions(token, sim_sets)

    def _on_load_error(self, token: int, stage: str, error_msg: str):
        if token != self._gen_token:
            return
        self._set_view(
            lambda: self._render_stage_error(stage, error_msg),
            f"⚠ {stage.capitalize()} failed — tap Continue to see details",
        )

    def _finalise_questions(self, token: int, sim_sets: list):
        if token != self._gen_token:
            return

        self._questions = question_generator.build_question_list(
            self._blueprint.entries, self._answer_matches, sim_sets
        )
        # Unfilled simulation slots (set had fewer questions than blueprint
        # slots) are skipped per spec, rather than shown blank.
        self._questions = [q for q in self._questions if q.question_text.strip()]

        # Apply shuffle preference (default: no shuffling)
        shuffle_prefs = config.get_shuffle_preferences()
        if shuffle_prefs['shuffle_enabled']:
            self._questions = question_generator.shuffle_questions(
                self._questions, shuffle_prefs['keep_sim_together']
            )

        if not self._questions:
            self._set_view(
                lambda: self._render_stage_error(
                    'question generation',
                    "No usable questions were produced. Please try again.",
                ),
                "⚠ Question generation problem — tap Continue to see details",
            )
            return

        self._start_quiz_with_questions(self._questions)

    def _start_quiz_with_questions(self, questions: list):
        """
        Shared quiz-start block: logs the questions into the quiz log and
        enters the quiz state. Used by both the legacy blueprint path
        (_finalise_questions) and the Agent 4 sequenced path
        (_on_sequenced_ready).
        """
        topics = self._blueprint.topic_names() if self._blueprint else []
        if not topics:
            seen = set()
            for q in questions:
                if q.topic and q.topic not in seen:
                    seen.add(q.topic)
                    topics.append(q.topic)

        self._quiz_log = quiz_logger.new_quiz_log(
            topics, evaluation_on=self._evaluation_on, skip_mode=self._current_skip_mode
        )
        for q in questions:
            quiz_logger.add_question(self._quiz_log, quiz_logger.QuestionRecord(
                index=q.index, number=q.number, question=q.question_text,
                section=q.section, q_type=q.q_type, is_simulation=q.is_simulation,
                correct_answer=q.correct_answer, options=q.options,
                topic=q.topic, sim_instruction=q.sim_instruction,
            ))

        self._current_idx = 0
        self._set_view(self._enter_quiz_state, "✓ Your quiz is ready — tap Continue to start")

    def _render_stage_error(self, stage: str, error_msg: str):
        tk.Label(self._body, text=f"Something went wrong during {stage}.", font=FONT_H3,
                 bg=C["content_bg"], fg=C["incorrect"]).pack(anchor="w", pady=(20, 6))
        tk.Label(self._body, text=error_msg, font=FONT_BODY, bg=C["content_bg"],
                 fg=C["text_secondary"], wraplength=560, justify="left").pack(anchor="w")

        retry_btn = tk.Label(self._body, text="← Back to Chat", font=("Segoe UI", 10, "bold"),
                              bg=C["accent_blue"], fg="white", padx=16, pady=8, cursor="hand2")
        retry_btn.pack(anchor="w", pady=(16, 0))
        retry_btn.bind("<Button-1>", lambda _: self._enter_chat_state())

    # ── QUIZ state ────────────────────────────────────────────────────────────
    def _enter_quiz_state(self):
        self._pipeline_stage = 'quiz'
        self._render_question()

    def _render_question(self):
        if self._current_idx >= len(self._questions):
            self._enter_done_state()
            return

        q = self._questions[self._current_idx]
        self._stage_lbl.config(text=f"Q {q.number} / {len(self._questions)}", bg=C["accent_blue"])
        self._clear_body()

        self._session_log.log_question(
            q.index, q.question_text, topic=q.topic, q_type=q.q_type,
            section=q.section, correct_answer=q.correct_answer,
            sim_instruction=q.sim_instruction,
        )

        pane = tk.PanedWindow(self._body, orient="horizontal", bg=C["content_bg"],
                               sashwidth=2, sashrelief="flat")
        pane.pack(fill="both", expand=True)

        left = tk.Frame(pane, bg=C["content_bg"])
        pane.add(left, minsize=340)
        right = tk.Frame(pane, bg=C["sidebar_bg"])
        pane.add(right, minsize=260)

        if q.is_simulation:
            self._render_sim_banner(left, q)

        q_frame = tk.Frame(left, bg=C["card_bg"], highlightbackground=C["border"], highlightthickness=1)
        q_frame.pack(fill="x")
        tk.Frame(q_frame, bg=C["accent_blue"], height=3).pack(fill="x")
        tk.Label(q_frame, text=q.question_text, font=("Segoe UI", 12),
                 bg=C["card_bg"], fg=C["text_primary"], wraplength=320, justify="left",
                 padx=20, pady=18).pack(fill="x")

        tk.Label(left, text="Your answer", font=("Segoe UI", 9, "bold"),
                 bg=C["content_bg"], fg=C["text_secondary"]).pack(anchor="w", pady=(16, 6))

        if q.q_type == 'MCQ' and q.options:
            self._mcq_var = tk.StringVar(value='')
            self._answer_text = None
            for opt in q.options:
                letter = self._option_letter(opt)
                tk.Radiobutton(
                    left, text=opt, variable=self._mcq_var, value=letter,
                    font=FONT_BODY, bg=C["content_bg"], fg=C["text_primary"],
                    selectcolor=C["card_bg"], anchor="w",
                ).pack(anchor="w", fill="x")
        elif q.q_type == 'MCQ' and not q.options:
            # Safety net: an MCQ with no options is otherwise a dead end
            # (this was issue #4 — bank-format mismatches can produce this;
            # regardless of cause, the UI must never trap the student here).
            tk.Label(left, text="⚠ No answer options were available for this question.",
                     font=FONT_LABEL, bg=C["content_bg"], fg=C["incorrect"],
                     wraplength=320, justify="left").pack(anchor="w", pady=(0, 8))
            self._mcq_var = None
            self._answer_text = tk.Text(
                left, font=FONT_BODY, height=4, bg=C["card_bg"], fg=C["text_primary"],
                relief="flat", padx=12, pady=10,
                highlightbackground=C["border"], highlightthickness=1,
                insertbackground=C["text_primary"],
            )
            self._answer_text.pack(fill="x")
        else:
            self._mcq_var = None
            self._answer_text = tk.Text(
                left, font=FONT_BODY, height=5, bg=C["card_bg"], fg=C["text_primary"],
                relief="flat", padx=12, pady=10,
                highlightbackground=C["border"], highlightthickness=1,
                insertbackground=C["text_primary"],
            )
            self._answer_text.pack(fill="x")

        ctrl = tk.Frame(left, bg=C["content_bg"])
        ctrl.pack(fill="x", pady=(16, 0))

        submit_btn = tk.Label(ctrl, text="Submit Answer", font=("Segoe UI", 10, "bold"),
                               bg=C["accent_blue"], fg="white", padx=18, pady=9, cursor="hand2")
        submit_btn.pack(side="left")
        submit_btn.bind("<Button-1>", lambda _: self._submit_answer(q))

        skip_btn = tk.Label(ctrl, text="Skip →", font=("Segoe UI", 10, "bold"),
                             bg=C["text_secondary"], fg="white", padx=14, pady=9, cursor="hand2")
        skip_btn.pack(side="left", padx=(8, 0))
        skip_btn.bind("<Button-1>", lambda _: self._skip_question(q))

        end_btn = tk.Label(ctrl, text="■ End & Get Report", font=("Segoe UI", 10, "bold"),
                            bg=C["incorrect"], fg="white", padx=14, pady=9, cursor="hand2")
        end_btn.pack(side="right")
        end_btn.bind("<Button-1>", lambda _: self._enter_done_state())

        self._build_feedback_panel(right)

    def _render_sim_banner(self, parent, q):
        sim_frame = tk.Frame(parent, bg=C["card_bg"], highlightbackground=C["accent"], highlightthickness=1)
        sim_frame.pack(fill="x", pady=(0, 12))
        tk.Frame(sim_frame, bg=C["accent"], height=3).pack(fill="x")
        tk.Label(sim_frame, text="🧪 SIMULATION REQUIRED", font=("Segoe UI", 9, "bold"),
                 bg=C["card_bg"], fg=C["accent"]).pack(anchor="w", padx=14, pady=(8, 2))
        tk.Label(sim_frame, text=q.sim_instruction or "Run the simulation before answering.",
                 font=FONT_LABEL, bg=C["card_bg"], fg=C["text_secondary"],
                 wraplength=320, justify="left").pack(anchor="w", padx=14, pady=(0, 6))
        launch_btn = tk.Label(sim_frame, text="▶ Launch Simulation", font=("Segoe UI", 9, "bold"),
                               bg=C["accent"], fg="white", padx=12, pady=6, cursor="hand2")
        launch_btn.pack(anchor="w", padx=14, pady=(0, 10))
        launch_btn.bind("<Button-1>", lambda _: self._launch_simulation(q))

    def _build_feedback_panel(self, right):
        tk.Label(right, text="Feedback", font=("Segoe UI", 11, "bold"),
                 bg=C["sidebar_bg"], fg=C["icon_active"]).pack(anchor="w", padx=20, pady=(24, 6))

        mode_note = ("Live evaluation ON — feedback appears after each written answer."
                     if self._evaluation_on else
                     "Evaluation OFF — written answers are scored at the end of the quiz.")
        tk.Label(right, text=mode_note, font=FONT_LABEL, bg=C["sidebar_bg"], fg=C["icon_inactive"],
                 wraplength=220, justify="left").pack(anchor="w", padx=20)
        tk.Frame(right, bg=C["sidebar_hover"], height=1).pack(fill="x", padx=16, pady=12)

        self._verdict_lbl = tk.Label(right, text="", font=("Segoe UI", 10, "bold"),
                                      bg=C["sidebar_bg"], fg=C["icon_active"], padx=20)
        self._verdict_lbl.pack(anchor="w")

        self._feedback_lbl = tk.Label(right, text="", font=FONT_LABEL, bg=C["sidebar_bg"],
                                       fg=C["icon_active"], wraplength=220, justify="left", padx=20)
        self._feedback_lbl.pack(anchor="w", pady=(6, 0))

        self._next_btn = tk.Label(right, text="Next Question →", font=("Segoe UI", 9, "bold"),
                                   bg=C["correct"], fg="white", padx=12, pady=6, cursor="hand2")
        self._next_btn.bind("<Button-1>", lambda _: self._advance())

    # ── Simulation launching ──────────────────────────────────────────────────
    def _option_letter(self, option_text: str) -> str:
        m = re.match(r'^([A-Da-d])[.)]', option_text.strip())
        return m.group(1).upper() if m else option_text.strip()[:1].upper()

    def _launch_simulation(self, q):
        folder = self._find_sim_folder(q.sim_name)
        if not folder:
            self._feedback_lbl.config(text=f"⚠ Couldn't locate simulation folder '{q.sim_name}'.")
            return
        try:
            folder_path = Path(folder)
            py_files   = sorted(folder_path.glob('*.py'))
            html_files = sorted(folder_path.glob('*.html'))
            if py_files:
                subprocess.Popen(['python3', str(py_files[0])], cwd=str(folder_path))
            elif html_files:
                webbrowser.open(f'file://{html_files[0].resolve()}')
            else:
                self._feedback_lbl.config(text="⚠ No launchable file (.py or .html) found.")
        except Exception as exc:
            self._feedback_lbl.config(text=f"⚠ Failed to launch simulation: {exc}")

    def _find_sim_folder(self, sim_name: str):
        for tf in self._topic_files:
            for sim in tf.get('sim_readmes', []):
                if sim['name'] == sim_name:
                    return sim['folder_path']
        return None

    # ── Skip ──────────────────────────────────────────────────────────────────
    def _skip_question(self, q):
        quiz_logger.mark_skipped(self._quiz_log, q.index)
        self._session_log.log_answer(q.index, '(skipped)')
        self._advance()

    # ── Answer submission ─────────────────────────────────────────────────────
    def _submit_answer(self, q):
        if q.q_type == 'MCQ' and q.options:
            self._submit_mcq(q)
        elif q.q_type == 'MCQ' and not q.options:
            self._submit_ungraded_fallback(q)
        else:
            self._submit_subj(q)

    def _submit_mcq(self, q):
        selected = self._mcq_var.get() if self._mcq_var else ''
        if not selected:
            self._feedback_lbl.config(text="Please select an option, or use Skip.")
            return

        is_correct = self._mcq_is_correct(selected, q.correct_answer)
        quiz_logger.update_answer(self._quiz_log, q.index, selected, is_correct=is_correct)
        self._session_log.log_answer(q.index, selected, is_correct=is_correct)

        self._verdict_lbl.config(
            text="✓ Correct" if is_correct else "✗ Incorrect",
            fg=C["correct"] if is_correct else C["incorrect"],
        )
        self._feedback_lbl.config(
            text="Nice work!" if is_correct else f"Correct answer: {q.correct_answer}"
        )
        self._show_next_button()

    def _submit_ungraded_fallback(self, q):
        """MCQ with no generated options — free-text fallback, never auto-graded."""
        answer = self._answer_text.get('1.0', 'end').strip() if self._answer_text else ''
        if not answer:
            self._feedback_lbl.config(text="Please write an answer, or use Skip.")
            return
        quiz_logger.update_answer(self._quiz_log, q.index, answer)
        self._session_log.log_answer(q.index, answer)
        self._verdict_lbl.config(text="Recorded (ungraded)", fg=C["text_secondary"])
        self._feedback_lbl.config(
            text="This question had no answer options, so it wasn't auto-graded. "
                 "Your response is saved for your own review."
        )
        self._show_next_button()

    def _mcq_is_correct(self, selected: str, correct: str) -> bool:
        selected = (selected or '').strip().upper()
        correct  = (correct or '').strip().upper()
        if not correct:
            return False
        return selected == correct[:1] or selected == correct

    def _submit_subj(self, q):
        answer = self._answer_text.get('1.0', 'end').strip() if self._answer_text else ''
        if not answer:
            self._feedback_lbl.config(text="Please write an answer, or use Skip.")
            return

        quiz_logger.update_answer(self._quiz_log, q.index, answer)
        self._session_log.log_answer(q.index, answer)

        if self._evaluation_on:
            self._verdict_lbl.config(text="Evaluating…", fg=C["icon_active"])
            self._feedback_lbl.config(text="")
            self._runner.evaluate_live(
                q.question_text, answer, q.correct_answer,
                on_result=lambda score, text: self._root.after(0, lambda: self._on_live_eval(q, answer, score, text)),
                on_error=lambda e: self._root.after(0, lambda: self._on_live_eval_error(e)),
            )
        else:
            self._verdict_lbl.config(text="Answer recorded", fg=C["text_secondary"])
            self._feedback_lbl.config(text="Evaluation disabled. This will be scored at the end.")
            self._show_next_button()

    def _on_live_eval(self, q, answer, score, visible_text):
        quiz_logger.update_answer(self._quiz_log, q.index, answer, score=score, ai_feedback=visible_text)
        self._session_log.log_feedback(q.index, visible_text, score=score)

        self._verdict_lbl.config(
            text=f"Score: {score:.2f}", fg=C["correct"] if score >= 0.5 else C["incorrect"]
        )
        self._feedback_lbl.config(text=visible_text)
        self._show_next_button()

    def _on_live_eval_error(self, error_msg):
        self._verdict_lbl.config(text="Evaluation failed", fg=C["incorrect"])
        self._feedback_lbl.config(text=error_msg)
        self._show_next_button()

    def _show_next_button(self):
        self._next_btn.pack(anchor="w", padx=20, pady=(14, 20))

    def _advance(self):
        self._current_idx += 1
        self._render_question()

    # ── DONE state ────────────────────────────────────────────────────────────
    def _enter_done_state(self):
        self._pipeline_stage = 'done'
        self._view = 'normal'
        self._stage_lbl.config(text="REPORT", bg=C["correct"])
        self._clear_body()

        # Never send a blank or skipped answer to the AI for scoring — this
        # is exactly what previously caused hallucinated positive feedback
        # on a quiz the student hadn't actually answered. Anything blank or
        # skipped is scored 0 locally, right here, before any batch call
        # goes out.
        to_score = []
        for q in self._questions:
            if q.q_type != 'SUBJ' or self._evaluation_on:
                continue
            record = self._get_record(q.index)
            if record and record.skipped:
                continue   # handled by skip_mode in mcq_score/subj_score
            if not record or not (record.user_answer or '').strip():
                quiz_logger.update_answer(
                    self._quiz_log, q.index, record.user_answer if record else '',
                    score=0.0, ai_feedback="No answer was given for this question.",
                )
                continue
            to_score.append(q)

        if to_score:
            self._render_loading("Scoring your written answers…")
            self._run_batch_evaluation(to_score)
        else:
            self._render_loading("Generating your summary report…")
            self._request_summary()

    def _get_record(self, index: int):
        for r in self._quiz_log.questions:
            if r.index == index:
                return r
        return None

    def _run_batch_evaluation(self, unscored_questions: list):
        groups = []
        for q in unscored_questions:
            record = self._get_record(q.index)
            groups.append({
                'number': str(q.number),
                'subquestions': [{
                    'label':          str(q.number),
                    'question':       q.question_text,
                    'user_answer':    record.user_answer if record else '',
                    'correct_answer': q.correct_answer,
                }],
            })

        def _on_result(results):
            for result in results:
                target_q = next((q for q in unscored_questions if str(q.number) == result.label), None)
                if target_q:
                    rec = self._get_record(target_q.index)
                    quiz_logger.update_answer(
                        self._quiz_log, target_q.index,
                        rec.user_answer if rec else '',
                        score=result.score,
                    )
            self._render_loading_and_summary()

        def _on_error(error_msg):
            self._clear_body()
            self._render_stage_error('batch scoring', error_msg)

        self._runner.evaluate_batch(
            groups,
            on_result=lambda r: self._root.after(0, lambda: _on_result(r)),
            on_error=lambda e: self._root.after(0, lambda: _on_error(e)),
        )

    def _render_loading_and_summary(self):
        self._clear_body()
        self._render_loading("Generating your summary report…")
        self._request_summary()

    def _request_summary(self):
        session_data = quiz_logger.format_for_summary(self._quiz_log)
        self._runner.generate_summary(
            session_data, self._quiz_log.topics,
            on_result=lambda r: self._root.after(0, lambda: self._on_summary_ready(r)),
            on_error=lambda e: self._root.after(0, lambda: self._on_summary_error(e)),
        )

    def _on_summary_ready(self, report_text: str):
        quiz_logger.mark_complete(self._quiz_log, report_text)
        self._render_report(report_text)

    def _on_summary_error(self, error_msg: str):
        quiz_logger.mark_complete(self._quiz_log, '')
        self._render_report(None, error_msg)

    def _render_report(self, report_text: Optional[str], error_msg: Optional[str] = None):
        self._clear_body()

        mcq_correct, mcq_total = self._quiz_log.mcq_score()
        subj_sum, subj_total   = self._quiz_log.subj_score()

        stats_row = tk.Frame(self._body, bg=C["content_bg"])
        stats_row.pack(fill="x", pady=(10, 16))
        if mcq_total:
            tk.Label(stats_row, text=f"MCQ: {mcq_correct}/{mcq_total}", font=FONT_H3,
                     bg=C["content_bg"], fg=C["text_primary"]).pack(side="left", padx=(0, 24))
        if subj_total:
            pct = round((subj_sum / subj_total) * 100, 1)
            tk.Label(stats_row, text=f"Written: {pct}%", font=FONT_H3,
                     bg=C["content_bg"], fg=C["text_primary"]).pack(side="left")

        skip_mode_note = ("skipped questions counted as 0" if self._quiz_log.skip_mode == 'zero'
                           else "skipped questions excluded from scoring")
        tk.Label(stats_row, text=f"  ({skip_mode_note})", font=FONT_LABEL,
                 bg=C["content_bg"], fg=C["text_secondary"]).pack(side="left")

        if error_msg:
            tk.Label(self._body, text=f"⚠ Summary generation failed: {error_msg}", font=FONT_BODY,
                     bg=C["content_bg"], fg=C["incorrect"], wraplength=560,
                     justify="left").pack(anchor="w", pady=(0, 12))
        elif report_text:
            report_box = tk.Text(self._body, font=FONT_BODY, bg=C["card_bg"], fg=C["text_primary"],
                                  relief="flat", wrap="word", padx=16, pady=14,
                                  highlightbackground=C["border"], highlightthickness=1, height=16)
            report_box.pack(fill="both", expand=True)
            report_box.insert("1.0", report_text)
            report_box.config(state="disabled")

        ctrl = tk.Frame(self._body, bg=C["content_bg"])
        ctrl.pack(fill="x", pady=(16, 0))

        new_btn = tk.Label(ctrl, text="Start New Quiz", font=("Segoe UI", 10, "bold"),
                            bg=C["accent_blue"], fg="white", padx=16, pady=9, cursor="hand2")
        new_btn.pack(side="left")
        new_btn.bind("<Button-1>", lambda _: self._reset_session())

        if self._on_navigate:
            review_btn = tk.Label(ctrl, text="Review This Quiz →", font=("Segoe UI", 10, "bold"),
                                   bg=C["correct"], fg="white", padx=16, pady=9, cursor="hand2")
            review_btn.pack(side="left", padx=(10, 0))
            review_btn.bind("<Button-1>", lambda _: self._on_navigate("review"))

    def _reset_session(self):
        self._pipeline_stage = 'idle'
        self._view = 'normal'
        self._current_render_fn = None
        self._gen_token += 1   # invalidate anything still in flight from the old session
        self._blueprint = None
        self._answer_matches = []
        self._questions = []
        self._current_idx = 0
        self._quiz_log = None
        self._session_log = SessionLog()
        self._sequenced_quiz = {}
        self._compliance_audit = {}
        self._start_new_session()
