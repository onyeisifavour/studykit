"""
evaluation_runner.py

Wraps all evaluation and conversational API calls:

  1. Pre-quiz chat              (CHAT state) - uses AgentRunner
  2. Live Section B evaluation  (QUIZ state, evaluation toggle ON)
  3. Batch Section B evaluation (DONE state, evaluation toggle OFF)
  4. Summary report generation  (DONE state)
  5. Evaluation thread messages (post-quiz tutoring)

All calls go through ApiClient.call() which runs in a daemon thread.

TKINTER THREAD SAFETY:
  EvaluationRunner calls on_result / on_error from the background thread.
  Wrap any callback that touches a Tkinter widget:

      runner.evaluate_live(
          ...,
          on_result=lambda s, e: root.after(0, lambda: update_ui(s, e)),
          on_error=lambda m: root.after(0, lambda: show_error(m)),
      )
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Optional

from . import prompts
from . import score_parser

if TYPE_CHECKING:
    from .api_client import ApiClient
    from .agent_runner import AgentRunner
    from .score_parser import ScoreResult


class EvaluationRunner:

    def __init__(self, api_client: ApiClient, agent_runner: Optional[AgentRunner] = None):
        self._api = api_client
        self._agent_runner = agent_runner

    # ── 1. Pre-quiz chat ───────────────────────────────────────────────────────

    def chat_message(
        self,
        message:      str,
        history:      list[dict],
        topic_files:  list[dict],
        on_result:    Callable[[str], None],
        on_error:     Callable[[str], None],
    ) -> None:
        """
        Sends one turn of the pre-quiz chat.

        Uses AgentRunner if available, otherwise falls back to
        the legacy prompt-based approach.

        history: list of {'role': 'user'|'assistant', 'content': str}
                 — the conversation so far, NOT including `message`
        topic_files: loaded topic dicts from library_scanner
        on_result(ai_reply): called with the tutor's response text
        """
        # Agent-based approach (new)
        if self._agent_runner:
            # Get preferences from config
            from . import config
            prefs = config.get_question_section_preferences()
            prefs['question_count'] = config.get('question_count', 10)
            
            is_first_turn = len(history) == 0
            teacher_message = history[-1]['content'] if history else None
            bg_runner = self._agent_runner

            def _on_reply(reply: str) -> None:
                # Fire the 4 background models in the background (don't wait).
                # This mirrors the Tkinter chat_view.py trigger so the Electron
                # path feeds the quota planner the same diagnostic reports.
                topic_context = ''
                try:
                    topic_context = prompts.build_multi_topic_concepts(
                        topic_files
                    )
                except Exception:
                    topic_context = ''
                bg_runner.send_to_background_models(
                    teacher_message=teacher_message if not is_first_turn else None,
                    student_message=message,
                    topic_digest=topic_context,
                )
                on_result(reply)

            self._agent_runner.call_main_chat(
                user_message=message,
                topic_files=topic_files,
                prefs=prefs,
                teacher_message=teacher_message if not is_first_turn else None,
                on_result=_on_reply,
                on_error=on_error,
            )
            return
        
        # Legacy prompt-based approach (old)
        topic_list = prompts.format_topic_list(topic_files)
        system     = prompts.CHAT_SYSTEM.format(topic_list=topic_list)

        self._api.call(
            system=system,
            user=message,
            history=history,
            on_success=on_result,
            on_error=on_error,
            max_tokens=500,
        )

    # ── 2. Live Section B evaluation (eval ON) ────────────────────────────────

    def evaluate_live(
        self,
        question:       str,
        user_answer:    str,
        correct_answer: str,
        on_result:      Callable[[float, str], None],
        on_error:       Callable[[str], None],
    ) -> None:
        """
        Evaluates a single Section B answer during the quiz (evaluation ON).

        The SCORE: line is stripped from the reply before showing it to the user
        so they see the explanation only (the score is handled programmatically).

        on_result(score: float, visible_explanation: str)
        """
        user_prompt = prompts.build_live_eval_prompt(
            question, user_answer, correct_answer
        )

        def _on_success(response: str) -> None:
            result  = score_parser.parse_single_score(response)
            visible = score_parser.strip_score_from_reply(response)
            on_result(result.score, visible)

        self._api.call(
            system=prompts.LIVE_EVAL_SYSTEM,
            user=user_prompt,
            on_success=_on_success,
            on_error=on_error,
            max_tokens=600,
        )

    # ── 3. Batch Section B evaluation (eval OFF) ──────────────────────────────

    def evaluate_batch(
        self,
        question_groups: list[dict],
        on_result:       Callable[[list[ScoreResult]], None],
        on_error:        Callable[[str], None],
    ) -> None:
        """
        Batch-evaluates all Section B answers at the end of a quiz
        when the evaluation toggle was OFF during the quiz.

        question_groups structure:
            [
              {
                'number': '1',
                'subquestions': [
                  {
                    'label':          '1a',
                    'question':       str,
                    'user_answer':    str,
                    'correct_answer': str,
                  },
                  ...
                ]
              },
              ...
            ]

        on_result(results: list[ScoreResult]) — one ScoreResult per sub-question
        """
        user_prompt = prompts.build_batch_eval_prompt(question_groups)

        def _on_success(response: str) -> None:
            results = score_parser.parse_multi_scores(response)
            on_result(results)

        self._api.call(
            system=prompts.BATCH_EVAL_SYSTEM,
            user=user_prompt,
            on_success=_on_success,
            on_error=on_error,
            max_tokens=1000,
        )

    # ── 3b. Theory batch grading (persistent quiz-note batches) ───────────────

    def evaluate_theory(
        self,
        theory_entries: list[dict],
        on_result:      Callable[[list[ScoreResult]], None],
        on_error:       Callable[[str], None],
    ) -> None:
        """
        Grades one theory batch (≤15 questions) on the bucketed 0–1 scale,
        returning one ScoreResult per question with the full EVALUATION note.

        theory_entries: list of {'label', 'question', 'user_answer',
                                 'correct_answer'} — see
                        theory_marker.eligible_entries().
        """
        user_prompt = prompts.build_theory_eval_prompt(theory_entries)

        # on_success arity differs between ApiClient (1 arg) and the CLI bridge
        # (2 args); take whichever arrives and read the leading argument.
        def _on_success(*args) -> None:
            response = args[0] if args else ''
            results = score_parser.parse_multi_scores(response)
            on_result(results)

        self._api.call(
            system=prompts.THEORY_EVAL_SYSTEM,
            user=user_prompt,
            on_success=_on_success,
            on_error=on_error,
            max_tokens=2000,
        )

    # ── 3c. Hybrid strict marking ─────────────────────────────────────────────

    def evaluate_hybrid(
        self,
        question:       str,
        user_answer:    str,
        correct_answer: str,
        on_result:      Callable[[bool, str], None],
        on_error:       Callable[[str], None],
    ) -> None:
        """
        Strict right/wrong marking of a Hybrid typed final answer. Used only
        after the deterministic fast path (hybrid_marker.hybrid_is_correct_strict)
        fails to confirm the answer.
        """
        user_prompt = prompts.build_hybrid_eval_prompt(
            question, user_answer, correct_answer
        )

        from .hybrid_marker import parse_hybrid_verdict

        def _on_success(*args) -> None:
            response = args[0] if args else ''
            is_correct, explanation = parse_hybrid_verdict(response)
            on_result(bool(is_correct), explanation)

        self._api.call(
            system=prompts.HYBRID_EVAL_SYSTEM,
            user=user_prompt,
            on_success=_on_success,
            on_error=on_error,
            max_tokens=400,
        )

    # ── 4. Summary report ──────────────────────────────────────────────────────

    def generate_summary(
        self,
        session_data: str,
        topics:       list[str],
        on_result:    Callable[[str], None],
        on_error:     Callable[[str], None],
    ) -> None:
        """
        Generates the end-of-quiz summary report.

        session_data: output of SessionLog.format_for_summary()
        topics:       list of topic name strings
        on_result(report_text)
        """
        user_prompt = prompts.build_summary_prompt(session_data, topics)

        self._api.call(
            system=prompts.SUMMARY_SYSTEM,
            user=user_prompt,
            on_success=on_result,
            on_error=on_error,
            max_tokens=1500,
        )

    # ── 5. Evaluation thread (post-quiz tutoring) ─────────────────────────────

    def eval_thread_message(
        self,
        question:       str,
        user_answer:    str,
        correct_answer: str,
        follow_up:      str,
        history:        list[dict],
        options:        Optional[list[str]]      = None,
        on_result:      Optional[Callable[[str], None]] = None,
        on_error:       Optional[Callable[[str], None]] = None,
    ) -> None:
        """
        Sends one turn of a post-quiz tutoring thread.

        question / user_answer / correct_answer: the question being discussed
        follow_up: the student's current message / question
        history:   the tutoring thread conversation so far
        options:   MCQ options (if the question is MCQ)
        on_result(ai_tutor_reply)
        """
        user_prompt = prompts.build_eval_thread_prompt(
            question, user_answer, correct_answer, follow_up, options
        )

        self._api.call(
            system=prompts.EVAL_THREAD_SYSTEM,
            user=user_prompt,
            history=history,
            on_success=on_result,
            on_error=on_error,
            max_tokens=1200,
        )

    # ── 6. Background model reports ────────────────────────────────────────────

    def get_background_reports(self) -> dict[str, str]:
        """
        Returns accumulated background model reports.

        Only available if AgentRunner is configured.
        Returns {agent_name: report_text} dict.
        """
        if self._agent_runner:
            return self._agent_runner.get_background_reports()
        return {}

    def resolve_background_reports(
        self,
        on_complete: Callable[[dict], None],
    ) -> None:
        """
        Resolve all outstanding background model messages and get final reports.

        Called when user clicks "Generate Quiz".
        """
        if self._agent_runner:
            self._agent_runner.resolve_pending_and_get_reports(
                on_complete=on_complete
            )
        else:
            on_complete({})

    # ── 7. Agent 1: Quota Planner ─────────────────────────────────────────────

    def call_quota_planner(
        self,
        background_reports: dict[str, str],
        user_request: str,
        total_questions: int,
        prefs: Optional[dict] = None,
        on_result=None,
        on_error=None,
    ) -> None:
        """
        Delegate to AgentRunner.call_quota_planner().

        Only available if AgentRunner is configured.
        """
        if self._agent_runner:
            self._agent_runner.call_quota_planner(
                background_reports=background_reports,
                user_request=user_request,
                total_questions=total_questions,
                prefs=prefs,
                on_result=on_result,
                on_error=on_error,
            )

    # ── 8. Agent 2: Query Specifier ──────────────────────────────────────────

    def call_query_specifier(
        self,
        quota_manifest: dict,
        topic_files: list[dict],
        prefs: Optional[dict] = None,
        on_result=None,
        on_error=None,
    ) -> None:
        """
        Delegate to AgentRunner.call_query_specifier().

        Only available if AgentRunner is configured.
        """
        if self._agent_runner:
            self._agent_runner.call_query_specifier(
                quota_manifest=quota_manifest,
                topic_files=topic_files,
                prefs=prefs,
                on_result=on_result,
                on_error=on_error,
            )

    # ── 9. Sim Track: Simulation Question Generator ──────────────────────────

    def call_sim_generator(
        self,
        sim_slots: list[dict],
        topic_files: list[dict],
        resolved_topics: Optional[dict] = None,
        on_result: Optional[Callable[[dict], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ) -> None:
        """
        Delegate to AgentRunner.call_sim_generator().

        Only available if AgentRunner is configured.
        """
        if self._agent_runner:
            self._agent_runner.call_sim_generator(
                sim_slots=sim_slots,
                topic_files=topic_files,
                resolved_topics=resolved_topics,
                on_result=on_result,
                on_error=on_error,
            )

    # ── 10. Agent 3: Candidate Selector ───────────────────────────────────────

    def call_candidate_selector(
        self,
        quota_manifest: dict,
        candidate_pool: dict,
        background_reports: dict[str, str],
        on_result=None,
        on_error=None,
    ) -> None:
        """
        Delegate to AgentRunner.call_candidate_selector().

        Only available if AgentRunner is configured.
        """
        if self._agent_runner:
            self._agent_runner.call_candidate_selector(
                quota_manifest=quota_manifest,
                candidate_pool=candidate_pool,
                background_reports=background_reports,
                on_result=on_result,
                on_error=on_error,
            )

    # ── 11. Agent 4: Pedagogical Sequence Builder ────────────────────────────

    def call_sequencer(
        self,
        selection_manifest: dict,
        background_reports: dict[str, str],
        on_result=None,
        on_error=None,
    ) -> None:
        """
        Delegate to AgentRunner.call_sequencer().

        Only available if AgentRunner is configured.
        """
        if self._agent_runner:
            self._agent_runner.call_sequencer(
                selection_manifest=selection_manifest,
                background_reports=background_reports,
                on_result=on_result,
                on_error=on_error,
            )

    # ── 12. Agent 5: Compliance Auditor ──────────────────────────────────────

    def call_compliance_audit(
        self,
        sequence_manifest: dict,
        background_reports: dict[str, str],
        user_request: str,
        missing_items: list[dict] | None = None,
        on_result=None,
        on_error=None,
    ) -> None:
        """
        Delegate to AgentRunner.call_compliance_audit().

        Only available if AgentRunner is configured.
        """
        if self._agent_runner:
            self._agent_runner.call_compliance_audit(
                sequence_manifest=sequence_manifest,
                background_reports=background_reports,
                user_request=user_request,
                missing_items=missing_items,
                on_result=on_result,
                on_error=on_error,
            )
