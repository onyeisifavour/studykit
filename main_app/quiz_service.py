"""
quiz_service.py

Headless orchestration for the StudyKit quiz pipeline, shared by the FastAPI
sidecar and (optionally) the Tkinter ui. It is transport-agnostic: it never
imports tkinter, HTTP, or the sidecar, so it can run anywhere.

It wraps the 5-agent generation chain that was historically embedded in
ui/quiz_page.py:

    CHAT  (optional, via chat_message)
    THINK : quota planner (Agent 1) -> query specifier (Agent 2) ->
            file retriever (code) -> candidate selector (Agent 3)
    LOAD  : sequencer (Agent 4) -> compliance audit (Agent 5) ->
            build_questions_from_sequence
    QUIZ  : evaluate_live / evaluate_batch
    DONE  : generate_summary

Design notes
------------
- All agent/API calls are delegated to AgentRunner / EvaluationRunner (which
  run in daemon threads). This module only *orchestrates* the chain and
  marshals results back through callbacks — it does not talk to the network
  or the UI itself.
- Callers pass a `progress` callback (stage, detail) to observe the chain.
- For configurations where the agent runner is unavailable, the legacy
  prompt-based path is kept as a fallback, mirroring quiz_page.py.
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Optional

from . import config
from . import file_retriever
from . import library_scanner
from . import prompts
from . import question_generator
from . import compliance_auditor
from .api_client import ApiClient, CLIBridgeClient
from .evaluation_runner import EvaluationRunner
from .manifest_validator import validate_candidate_pool


class QuizServiceError(Exception):
    pass


# The stage labels map to the Electron pipeline UI's 4 stages.
STAGES = {
    'planning': 'Planning',
    'finding':  'Finding questions',
    'ordering': 'Ordering',
    'auditing': 'Final checks',
}


def _topics_from_questions(questions: list) -> list[str]:
    """Collect a topic label list from GeneratedQuestion.topic fields."""
    seen: list[str] = []
    for q in questions:
        t = (getattr(q, 'topic', '') or '').strip()
        if t and t not in seen:
            seen.append(t)
    return seen


class QuizService:
    """Holds the shared ApiClient / AgentRunner / EvaluationRunner and provides
    the orchestration methods used by the sidecar (and Tkinter)."""

    def __init__(
        self,
        api_client: Optional[Any] = None,
        agent_runner: Optional[Any] = None,
        evaluation_runner: Optional[EvaluationRunner] = None,
    ):
        if api_client is None:
            api_client, agent_runner = self._build_clients()
        self._api: Optional[Any] = api_client
        self._agent_runner = agent_runner
        self._runner = evaluation_runner or EvaluationRunner(api_client, agent_runner)  # type: ignore

    def _build_clients(self) -> tuple[Any, Any]:
        """Construct ApiClient + optional AgentRunner from current config
        (CLI bridge by default, direct-API failover otherwise)."""
        if config.get_provider_mode() == 'cli_bridge':
            from .agent_runner import AgentRunner
            client: Any = CLIBridgeClient(model=config.get_cli_model())
            return client, AgentRunner(client)
        client: Any = ApiClient(
            groq_keys=config.get('groq_keys', []),
            openrouter_keys=config.get('openrouter_keys', []),
            groq_model=config.get('groq_model') or None,
            openrouter_model=config.get('openrouter_model') or None,
            custom_url=config.get('custom_api_url', ''),
            custom_key=config.get('custom_api_key', ''),
            custom_model=config.get('custom_model', ''),
        )
        return client, None

    @property
    def evaluation_runner(self) -> EvaluationRunner:
        return self._runner

    @property
    def has_agent_runner(self) -> bool:
        return self._agent_runner is not None

    # ── 1. Pre-quiz chat ──────────────────────────────────────────────────────
    def chat_message(
        self,
        message: str,
        history: list[dict],
        topic_files: list[dict],
        on_result: Callable[[str], None],
        on_error: Callable[[str], None],
    ) -> None:
        self._runner.chat_message(message, history, topic_files, on_result, on_error)

    # ── 1b. Post-quiz tutoring thread ─────────────────────────────────────────
    def tutor_message(
        self,
        question: str,
        user_answer: str,
        correct_answer: str,
        follow_up: str,
        history: list[dict],
        options: Optional[list[str]] = None,
        on_result: Optional[Callable[[str], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ) -> None:
        """One turn of post-quiz tutoring. Prefers the CLI-bridge main chat
        agent (works in cli_bridge provider mode); falls back to the direct-API
        evaluation-thread prompt otherwise."""
        if self._agent_runner is not None:
            context = (
                f"QUESTION: {question}"
                + (f"\n\nOPTIONS:\n" + "\n".join(f"- {o}" for o in options) if options else "")
                + f"\n\nSTUDENT'S ANSWER: {user_answer}"
                + f"\n\nCORRECT ANSWER: {correct_answer}"
            )
            history_block = "\n".join(
                f"{'Student' if m.get('role') == 'user' else 'Tutor'}: {m.get('content')}"
                for m in history
            )
            prompt = (
                "You are a patient, knowledgeable tutor helping a student review a "
                "specific question from their completed quiz. Explain the concept "
                "clearly, address the misconception in the student's answer, and "
                "answer their follow-up in context. Be thorough but clear.\n\n"
                + prompts.MATH_NOTATION_SPEC + "\n\n"
                f"{context}\n\n"
                + (f"TUTORING THREAD SO FAR:\n{history_block}\n\n" if history_block else "")
                + f"STUDENT'S FOLLOW-UP: {follow_up}"
            )
            self._agent_runner.call_main_chat(
                user_message=prompt,
                topic_files=[],
                prefs={'section_a_sim': True, 'section_a_nonsim': True,
                       'section_b_sim': True, 'section_b_nonsim': True,
                       'question_count': 'Not specified'},
                teacher_message=None,
                on_result=on_result,
                on_error=on_error,
            )
            return

        self._runner.eval_thread_message(
            question=question,
            user_answer=user_answer,
            correct_answer=correct_answer,
            follow_up=follow_up,
            history=history,
            options=options,
            on_result=on_result,
            on_error=on_error,
        )

    # ── Generation chain ──────────────────────────────────────────────────────
    def generate_quiz(
        self,
        user_request: str,
        topic_files: list[dict],
        history: Optional[list[dict]] = None,
        total_questions: Optional[int] = None,
        prefs: Optional[dict] = None,
        progress: Optional[Callable[[str, str], None]] = None,
        on_result: Optional[Callable[[list, dict], None]] = None,
        on_error: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        """
        Runs the full 5-agent generation chain and, on success, calls
        on_result(questions, meta) with the ordered list of GeneratedQuestion
        and a small meta dict (topics, audit result).

        progress(stage, detail) fires as each stage is entered (stage is one
        of STAGES keys). The chain is asynchronous: results arrive via
        callbacks. Use generate_quiz_sync() to block until completion.

        prefs: question section preferences (section_a_sim/nonsim,
               section_b_sim/nonsim). Defaults to the saved settings when None.
        """
        if not self._agent_runner:
            self._legacy_generate(user_request, topic_files, history,
                                  total_questions, progress, on_result, on_error)
            return

        if total_questions is None:
            total_questions = int(config.get('question_count') or 10)  # type: ignore
        qcount: int = total_questions
        if prefs is None:
            prefs = config.get_question_section_preferences()

        # ── Inject manifest-based request block ────────────────────────────
        from .user_selections import load_manifest, build_request_block
        manifest = load_manifest()
        user_request = build_request_block(manifest, user_request, form_prefs=prefs)
        # Gate on the outstanding background-model reports: the Electron chat
        # fires the 4 background agents asynchronously per turn, so by the time
        # the user clicks Generate Quiz there may still be in-flight / stacked
        # messages. Block for them (bounded) so the quota planner sees the
        # current diagnostic picture, matching the Tkinter path.
        background_reports = self._agent_runner.resolve_pending_and_get_reports_sync(timeout=60.0)

        def _ptrain(stage: str, detail: str):
            if progress:
                progress(stage, detail)

        try:
            _ptrain('planning', 'Parsing chat history and generating a quiz blueprint…')
            self._runner.call_quota_planner(
                background_reports=background_reports,
                user_request=user_request,
                total_questions=qcount,
                prefs=prefs,
                on_result=lambda m: self._on_quota_manifest(
                    m, user_request, topic_files, prefs, progress, on_result, on_error),
                on_error=lambda e: _fail(on_error, 'planning', e),
            )
        except Exception as exc:  # pragma: no cover - defensive
            _fail(on_error, 'planning', str(exc))

    # ── Chain continuation (agent path) ──────────────────────────────────────
    def _on_quota_manifest(self, manifest, user_request, topic_files, prefs,
                           progress, on_result, on_error):
        from .sim_generator import resolve_slot_formats, split_slots_by_format

        config.save_quota_manifest(manifest)
        resolve_slot_formats(manifest, prefs)
        non_sim_slots, sim_slots = split_slots_by_format(manifest)
        if sim_slots and non_sim_slots:
            detail = 'Building simulation questions and scoring bank candidates…'
        elif sim_slots:
            detail = 'Building simulation questions from your topic READMEs…'
        else:
            detail = 'Scoring and filtering candidate questions from your banks…'
        _progress(progress, 'finding', detail)
        self._runner.call_query_specifier(
            quota_manifest=manifest,
            topic_files=topic_files,
            prefs=prefs,
            on_result=lambda spec: self._on_query_spec(
                manifest, spec, user_request, topic_files, prefs, progress, on_result, on_error),
            on_error=lambda e: _fail(on_error, 'finding', e),
        )

    def _on_query_spec(self, quota_manifest, spec_manifest, user_request,
                       topic_files, prefs, progress, on_result, on_error):
        from .sim_generator import (
            filter_manifest_by_slots,
            merge_selection_manifests,
            resolve_slot_formats,
            split_slots_by_format,
        )

        resolve_slot_formats(quota_manifest, prefs)
        non_sim_slots, sim_slots = split_slots_by_format(quota_manifest)
        non_sim_manifest = filter_manifest_by_slots(quota_manifest, non_sim_slots)

        non_sim_numbers = {
            s['slot_number'] for s in non_sim_slots if isinstance(s, dict)
        }

        resolved_topics = {}
        for spec in spec_manifest.get('file_query_specs', []):
            tiers = spec.get('search_tiers', {}) or {}
            tier_one = tiers.get('tier_1_exact') or {}
            resolved_topics[spec.get('slot_number')] = tier_one.get('topic', '')

        # The question banks are only engaged when there is at least one
        # Non-Sim slot. A fully-sim quiz never scans or retrieves bank content,
        # so the pool is left empty and no validation runs.
        pool: dict = {}
        bg = self._agent_runner.get_background_reports() if self._agent_runner else {}
        if non_sim_slots:
            non_sim_spec_manifest = {
                **spec_manifest,
                'file_query_specs': [
                    spec for spec in spec_manifest.get('file_query_specs', [])
                    if isinstance(spec, dict) and spec.get('slot_number') in non_sim_numbers
                ],
            }
            pool = file_retriever.retrieve_candidates(non_sim_spec_manifest, topic_files)
            errors = validate_candidate_pool(pool)
            if errors:
                _fail(on_error, 'finding', 'Candidate pool failed validation: ' + '; '.join(errors))
                return

        non_sim_pool = {
            k: v for k, v in pool.items() if k in non_sim_numbers
        }

        state = {
            'lock': threading.Lock(),
            'pending': set(),
            'result': {},
            'failed': '',
        }

        def _finish_track(name: str, manifest) -> None:
            with state['lock']:
                if state['failed']:
                    return
                state['result'][name] = manifest
                state['pending'].discard(name)
                if state['pending']:
                    return
            merged = merge_selection_manifests(
                state['result'].get('non_sim'),
                state['result'].get('sim'),
            )
            self._on_selection(merged, user_request, progress, on_result, on_error)

        def _fail_track(name: str, msg: str) -> None:
            with state['lock']:
                if state['failed']:
                    return
                state['failed'] = msg
            _fail(on_error, 'finding', msg)

        no_tracks = not non_sim_slots and not sim_slots

        if non_sim_slots:
            _progress(progress, 'finding',
                      'Scoring and filtering candidate questions from your banks…')
            state['pending'].add('non_sim')
            self._runner.call_candidate_selector(
                quota_manifest=non_sim_manifest,
                candidate_pool=non_sim_pool,
                background_reports=bg,
                on_result=lambda sel: _finish_track('non_sim', sel),
                on_error=lambda e: _fail_track('non_sim', e),
            )
        else:
            state['result']['non_sim'] = None

        if sim_slots:
            _progress(progress, 'finding',
                      'Building simulation questions from your topic READMEs…')
            state['pending'].add('sim')
            self._runner.call_sim_generator(
                sim_slots=sim_slots,
                topic_files=topic_files,
                resolved_topics=resolved_topics,
                on_result=lambda sel: _finish_track('sim', sel),
                on_error=lambda e: _fail_track('sim', e),
            )
        else:
            state['result']['sim'] = None

        if no_tracks:
            merged = merge_selection_manifests(
                state['result'].get('non_sim'),
                state['result'].get('sim'),
            )
            self._on_selection(merged, user_request, progress, on_result, on_error)

    def _on_selection(self, selection_manifest, user_request, progress,
                      on_result, on_error):
        config.save_selected_items(selection_manifest)
        _progress(progress, 'ordering', 'Applying pacing model: Warm-up → Repair → Core → Transfer…')
        bg = self._agent_runner.get_background_reports() if self._agent_runner else {}
        self._runner.call_sequencer(
            selection_manifest=selection_manifest,
            background_reports=bg,
            on_result=lambda seq: self._on_sequenced(
                seq, selection_manifest, user_request, progress, on_result, on_error),
            on_error=lambda e: _fail(on_error, 'ordering', e),
        )

    def _on_sequenced(self, sequence_manifest, selection_manifest, user_request,
                      progress, on_result, on_error):
        config.save_sequenced_quiz(sequence_manifest)

        # ── Machine-check: compare manifest against plan before LLM audit ──
        from .user_selections import (load_manifest,
                                      check_manifest_against_plan,
                                      check_math_notation)
        user_manifest = load_manifest()
        manifest_violations = check_manifest_against_plan(user_manifest, sequence_manifest)
        math_violations = check_math_notation(sequence_manifest)
        blocks = []
        if manifest_violations:
            blocks.append(
                "\n\n=== MACHINE-CHECKED VIOLATIONS (deterministic — these are "
                "DEFINITE failures) ===\n"
                + "\n".join(f"- {v}" for v in manifest_violations)
            )
        if math_violations:
            blocks.append(
                "\n\n=== MATH-NOTATION ADVISORY (deterministic, NON-BLOCKING) ===\n"
                "The following Sim-slot text uses plain-ASCII math instead of "
                "delimited LaTeX. The app normalises and renders it regardless, "
                "so do NOT fail the audit over formatting alone. Note the "
                "issues and correct them if re-authoring that content.\n"
                + "\n".join(f"- {v}" for v in math_violations)
            )
        if blocks:
            # Feed violations explicitly into the audit so 5c sees them rather
            # than having to re-derive intent from chat.
            user_request = user_request + ''.join(blocks)

        _progress(progress, 'auditing', 'Checking question types, count, and compliance constraints…')
        bg = self._agent_runner.get_background_reports() if self._agent_runner else {}
        missing = selection_manifest.get('missing_items', [])
        self._runner.call_compliance_audit(
            sequence_manifest=sequence_manifest,
            background_reports=bg,
            user_request=user_request,
            missing_items=missing,
            on_result=lambda result, payload: self._on_audited(
                payload, progress, on_result, on_error),
            on_error=lambda e: _fail(on_error, 'auditing', e),
        )

    def _on_audited(self, payload, progress, on_result, on_error):
        manifest = compliance_auditor.rebuild_sequence_manifest(payload)
        if progress:
            progress('auditing', 'Final checks passed — building your quiz…')
        self._finish_questions(manifest, progress, on_result)

    def _finish_questions(self, sequence_manifest, progress, on_result):
        # Prefer the original saved manifest: it preserves the true per-slot
        # source ('sim_generated' vs 'bank') and the pacing metadata that the
        # sanitised audit payload flattens. Content is identical.
        from . import quiz_note
        orig = config.get_sequenced_quiz()
        if isinstance(orig, dict) and orig.get('ordered_quiz_sequence'):
            sequence_manifest = orig
        questions = question_generator.build_questions_from_sequence(sequence_manifest)
        questions = [q for q in questions if q.question_text.strip()]
        if not questions:
            # No usable questions: surface via a normal error callback path.
            _on_error = None
            # We don't have on_error here; delegate by calling a small hook.
            self._no_questions(progress, on_result)
            return
        shuffle_prefs = config.get_shuffle_preferences()
        if shuffle_prefs['shuffle_enabled']:
            questions = question_generator.shuffle_questions(
                questions, shuffle_prefs['keep_sim_together'])
        topics = _topics_from_questions(questions)
        quiz_note.ensure_note(questions, {'topics': topics}, sequence_manifest)
        if on_result:
            on_result(questions, {'topics': topics})

    def _no_questions(self, progress, on_result):
        # No-error-callback variant; the sidecar treats an empty result as an
        # error at the API layer.
        if on_result:
            on_result([], {'topics': [], 'empty': True})

    # ── Legacy (no-agent) fallback ────────────────────────────────────────────
    def _legacy_generate(self, user_request, topic_files, history,
                         total_questions, progress, on_result, on_error):
        """Mirrors quiz_page.py's prompt-based path for agent-less configs."""
        from . import prompts

        if progress:
            progress('planning', 'Generating a quiz blueprint…')
        # The legacy path requires the interactive blueprint load flow, which is
        # not reproduced headlessly. Signal unsupported clearly.
        _fail(on_error, 'planning',
              'QuizService requires an AgentRunner (cli_bridge) to generate '
              'quizzes headlessly. Please configure provider_mode and register '
              'the pipeline agents.')

    # ── Synchronous wrappers ──────────────────────────────────────────────────
    def generate_quiz_sync(
        self,
        user_request: str,
        topic_files: Optional[list[dict]] = None,
        total_questions: Optional[int] = None,
        history: Optional[list[dict]] = None,
        prefs: Optional[dict] = None,
    ) -> tuple[list, dict]:
        """
        Blocking variant of generate_quiz(). Returns (questions, meta).

        Raises QuizServiceError on failure. Used by the sidecar's synchronous
        generation path and by tests.
        """
        if topic_files is None:
            topic_files = self.load_selected_topics()

        done = threading.Event()
        result: dict = {}
        errors: dict = {}

        def _res(questions, meta):
            result['questions'] = questions
            result['meta'] = meta
            done.set()

        def _err(stage, msg):
            errors['message'] = msg
            done.set()

        self.generate_quiz(
            user_request=user_request,
            topic_files=topic_files,
            total_questions=total_questions,
            history=history,
            prefs=prefs,
            on_result=_res,
            on_error=_err,
        )
        if not done.wait(timeout=900):
            raise QuizServiceError('Quiz generation timed out.')
        if 'message' in errors:
            raise QuizServiceError(errors['message'])
        return result['questions'], result['meta']

    def load_selected_topics(self) -> list[dict]:
        return library_scanner.load_selected_topics(config.get_selected_topics())

    def selected_topic_paths(self) -> list[str]:
        return config.get_selected_topics()

    # ── Live evaluation ───────────────────────────────────────────────────────
    def evaluate_live(
        self,
        question: str,
        user_answer: str,
        correct_answer: str,
        on_result: Callable[[float, str], None],
        on_error: Callable[[str], None],
    ) -> None:
        self._runner.evaluate_live(question, user_answer, correct_answer,
                                   on_result, on_error)

    def evaluate_batch(
        self,
        question_groups: list[dict],
        on_result: Callable[[list], None],
        on_error: Callable[[str], None],
    ) -> None:
        self._runner.evaluate_batch(question_groups, on_result, on_error)

    def evaluate_theory(
        self,
        theory_entries: list[dict],
        on_result: Callable[[list], None],
        on_error: Callable[[str], None],
    ) -> None:
        """Bucketed 0–1 grading of one theory batch file (≤15 questions)."""
        self._runner.evaluate_theory(theory_entries, on_result, on_error)

    def evaluate_hybrid(
        self,
        question: str,
        user_answer: str,
        correct_answer: str,
        on_result: Callable[[bool, str], None],
        on_error: Callable[[str], None],
    ) -> None:
        """Strict AI fallback marking of a Hybrid final answer."""
        self._runner.evaluate_hybrid(question, user_answer, correct_answer,
                                     on_result, on_error)

    def generate_summary(
        self,
        session_data: str,
        topics: list[str],
        on_result: Callable[[str], None],
        on_error: Callable[[str], None],
    ) -> None:
        self._runner.generate_summary(session_data, topics, on_result, on_error)


def _progress(cb, stage: str, detail: str):
    if cb:
        cb(stage, detail)


def _fail(on_error, stage: str, msg: str):
    if on_error:
        on_error(stage, msg)


class GenerationJob:
    """
    Thin, thread-safe wrapper around QuizService.generate_quiz() that exposes
    a pollable state for transport layers (e.g. the sidecar). Run it in a
    worker thread via start().

    States: pending -> running -> done | error | cancelled
    """

    def __init__(
        self,
        service: QuizService,
        user_request: str,
        topic_files: Optional[list] = None,
        total_questions: Optional[int] = None,
        history: Optional[list[dict]] = None,
        prefs: Optional[dict] = None,
    ):
        self._service = service
        self._user_request = user_request
        self._topic_files = topic_files or service.load_selected_topics()
        self._total_questions = total_questions
        self._history = history or []
        self._prefs = prefs

        self._lock = threading.Lock()
        self.state = 'pending'
        self.stage: str = ''
        self.detail: str = ''
        self.result: Optional[tuple] = None   # (questions, meta)
        self.error: Optional[str] = None
        self._cancelled = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        """Marks the job cancelled. The in-flight agent call keeps running in
        the background, but its callbacks become no-ops (mirrors the Tkinter
        kill-token behaviour)."""
        self._cancelled.set()
        with self._lock:
            if self.state in ('pending', 'running'):
                self.state = 'cancelled'

    def is_finished(self) -> bool:
        with self._lock:
            return self.state in ('done', 'error', 'cancelled')

    def snapshot(self) -> dict:
        with self._lock:
            return {
                'state':  self.state,
                'stage':  self.stage,
                'detail': self.detail,
                'error':  self.error,
                'ready':  self.state == 'done' and self.result is not None,
            }

    def _run(self) -> None:
        with self._lock:
            if self._cancelled.is_set():
                self.state = 'cancelled'
                return
            self.state = 'running'

        def _progress(stage: str, detail: str):
            if self._cancelled.is_set():
                return
            with self._lock:
                self.stage = stage
                self.detail = detail

        def _result(questions, meta):
            if self._cancelled.is_set():
                return
            with self._lock:
                self.result = (questions, meta)
                self.state = 'done'

        def _error(stage: str, msg: str):
            if self._cancelled.is_set():
                return
            with self._lock:
                self.error = msg
                self.state = 'error'

        self._service.generate_quiz(
            user_request=self._user_request,
            topic_files=self._topic_files,
            total_questions=self._total_questions,
            history=self._history,
            prefs=self._prefs,
            progress=_progress,
            on_result=_result,
            on_error=_error,
        )
