"""
sidecar/app.py

FastAPI sidecar served over localhost. Thin adapter — all logic lives in the
existing main_app modules; this layer only translates HTTP requests into those
calls and returns the JSON shapes documented in UI_UX_DESIGN_HANDOFF.md §7.
"""

import json
import re
import threading
import uuid
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response

from .. import config
from .. import sim_assets
from .. import sim_html
from .. import dashboard_stats
from .. import flashcard_builder
from .. import library_scanner
from .. import quiz_logger
from .. import quiz_artifact
from .. import quiz_instance
from ..user_selections import normalize_ascii_math
from ..quiz_service import QuizService, GenerationJob

app = FastAPI(title="StudyKit sidecar", version="0.1.0")

# A single shared generation service (owns ApiClient/AgentRunner/EvaluationRunner).
_service: QuizService | None = None


def _get_service() -> QuizService:
    global _service
    if _service is None:
        _service = QuizService()
    return _service


def _invalidate_service() -> None:
    """Drop the cached service so the next request rebuilds from new config."""
    global _service
    _service = None


# In-memory registry of running generation jobs (transport layer only).
_JOBS: dict[str, GenerationJob] = {}
_JOBS_LOCK = threading.Lock()

# Stored API keys are never echoed back to the renderer. A masked placeholder
# is returned so the Settings screen can show whether a key exists; on save,
# a value equal to the placeholder is treated as "leave unchanged".
MASKED_KEY = '••••••••'

# The Electron renderer loads from http://localhost (dev server) or file://
# (built app), so the origin is never a remote site. Permit all local origins;
# this sidecar only ever binds to 127.0.0.1.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get('/health')
def health() -> dict:
    return {"ok": True, "name": "studykit", "version": app.version}


@app.get('/api/dashboard')
def dashboard() -> dict:
    return dashboard_stats.build_dashboard()


def _log_overall(log) -> float:
    """Per-quiz average on 0–1, honouring skip_mode (mirrors the dashboard)."""
    credits = [
        c for q in log.questions
        for c in [dashboard_stats._question_credit(log, q)]
        if c is not None
    ]
    if not credits:
        return 0.0
    return sum(c for c, _ in credits) / len(credits)


def _log_topic(log) -> str:
    return (log.topics[0] if log.topics else '').strip()


@app.get('/api/history')
def history() -> dict:
    logs = []
    for s in quiz_logger.list_quiz_logs():
        log = quiz_logger.load_quiz_log(s['quiz_id'])
        if log is None:
            continue
        topic = _log_topic(log)
        logs.append({
            'quiz_id':     log.quiz_id,
            'topic':       topic,
            'subject':     dashboard_stats._subject_of(topic),
            'created_at':  log.created_at,
            'completed':   log.completed,
            'total':       len(log.questions),
            'correct':     sum(1 for q in log.questions if q.is_correct),
            'skipped':     sum(1 for q in log.questions if q.skipped),
            'avg_pct':     round(_log_overall(log) * 100),
            'skip_mode':   log.skip_mode,
            'marking_pending': log.marking_pending,
        })
    return {'quizzes': logs}


@app.get('/api/history/{quiz_id}')
def history_detail(quiz_id: str) -> dict:
    log = quiz_logger.load_quiz_log(quiz_id)
    if log is None:
        raise HTTPException(status_code=404, detail='quiz not found')
    return {
        'quiz_id':  log.quiz_id,
        'topic':    _log_topic(log),
        'subject':  dashboard_stats._subject_of(_log_topic(log)),
        'created_at': log.created_at,
        'skip_mode':  log.skip_mode,
        'marking_pending': log.marking_pending,
        'questions': [{
            'number':         q.number,
            'question':       normalize_ascii_math(q.question),
            'options':        [normalize_ascii_math(o) for o in (q.options or [])],
            'section':        q.section,
            'q_type':         q.q_type,
            'is_simulation':  q.is_simulation,
            'topic':          q.topic,
            'user_answer':    normalize_ascii_math(q.user_answer),
            'correct_answer': normalize_ascii_math(q.correct_answer),
            'is_correct':     q.is_correct,
            'score':          q.score,
            'skipped':        q.skipped,
            'ai_feedback':    normalize_ascii_math(q.ai_feedback),
        } for q in log.questions],
    }


@app.delete('/api/history/{quiz_id}')
def history_delete(quiz_id: str) -> dict:
    """
    Removes one History entry. Only the log is deleted — any stored artifact
    or instance built from this quiz is left alone so it can still be retaken.
    """
    try:
        deleted = quiz_logger.delete_quiz_log(quiz_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail='quiz not found')
    return {'deleted': True, 'quiz_id': quiz_id}


@app.post('/api/history/{quiz_id}/to-artifact')
def history_to_artifact(quiz_id: str) -> dict:
    """
    Retake: turns a completed History entry into an immutable artifact so the
    same quiz can be taken again. The history entry itself is not modified.
    """
    try:
        artifact_id = quiz_artifact.artifact_from_history(quiz_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {'artifact_id': artifact_id, 'source_quiz_id': quiz_id}


# ── Artifacts (immutable quiz sets) ───────────────────────────────────────────

@app.get('/api/artifacts')
def artifacts_list() -> dict:
    return {'artifacts': quiz_artifact.list_artifacts()}


@app.get('/api/artifacts/{artifact_id}')
def artifacts_detail(artifact_id: str) -> dict:
    rec = quiz_artifact.load_artifact(artifact_id)
    if rec is None:
        raise HTTPException(status_code=404, detail='artifact not found')
    return {
        'artifact_id':  rec.get('artifact_id', artifact_id),
        'created_at':   rec.get('created_at', ''),
        'source':       rec.get('source', ''),
        'topics':       rec.get('topics', []),
        'subject':      (rec.get('subjects') or ['Other'])[0],
        'title':        (rec.get('topics') or ['Untitled quiz'])[0],
        'total_questions': rec.get('total_questions', 0),
        'questions': [{
            'number':          q.get('number', 0),
            'section':         q.get('section', ''),
            'q_type':          q.get('type', ''),
            'question_text':   normalize_ascii_math(str(q.get('question_text', ''))),
            'options':         [normalize_ascii_math(str(o)) for o in (q.get('options') or [])],
            'correct_answer':  normalize_ascii_math(str(q.get('correct_answer', ''))),
            'correct_option_index': q.get('correct_option_index'),
            'option_rationales':    [str(r) for r in (q.get('option_rationales') or [])],
            'option_error_types':   [str(t) for t in (q.get('option_error_types') or [])],
            'topic':           q.get('topic', ''),
            'is_simulation':   bool(q.get('is_simulation', False)),
            'sim_instruction': normalize_ascii_math(str(q.get('sim_instruction', ''))),
        } for q in rec.get('questions', [])],
    }


@app.post('/api/artifacts/{artifact_id}/derive')
def artifacts_derive(artifact_id: str, body: dict | None = None) -> dict:
    """
    Creates a new, independent artifact from an existing one. `numbers` is the
    caller's full ordered wish-list of source question numbers — it drives
    removal, subsetting and reordering at once. The result is renumbered 1..N.
    Omit `numbers` to duplicate the whole set unchanged.
    """
    body = body or {}
    numbers = body.get('numbers')
    source = str(body.get('source') or 'edit')
    try:
        new_id = quiz_artifact.derive_artifact(
            artifact_id, None if numbers is None else list(numbers), source=source)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {'artifact_id': new_id, 'created': new_id != artifact_id}


@app.delete('/api/artifacts/{artifact_id}')
def artifacts_delete(artifact_id: str) -> dict:
    try:
        deleted = quiz_artifact.delete_artifact(artifact_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail='artifact not found')
    return {'deleted': True, 'artifact_id': artifact_id}


# ── Instances (mutable attempts) ──────────────────────────────────────────────

@app.get('/api/instances')
def instances_list() -> dict:
    return {'instances': quiz_instance.list_instances()}


def _instance_detail(instance_id: str) -> dict:
    """Detail for an instance we have just written, so it must exist."""
    rec = quiz_instance.detail(instance_id)
    if rec is None:
        raise HTTPException(status_code=404, detail='instance not found')
    return rec


@app.get('/api/instances/{instance_id}')
def instances_detail(instance_id: str) -> dict:
    return _instance_detail(instance_id)


@app.post('/api/artifacts/{artifact_id}/start')
def instances_start(artifact_id: str) -> dict:
    """Begins a new attempt at an artifact. The artifact is only read."""
    try:
        rec = quiz_instance.start_instance(artifact_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _instance_detail(rec['instance_id'])


@app.post('/api/quiz/{quiz_id}/adopt-instance')
def quiz_adopt_instance(quiz_id: str) -> dict:
    """Attaches an instance to a working note that already exists.

    A pipeline-generated quiz already has a note holding the student's answers,
    so Save State adopts that note rather than copying the quiz into a new one.
    """
    try:
        rec = quiz_instance.adopt_note(quiz_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _instance_detail(rec['instance_id'])


@app.post('/api/instances/{instance_id}/save-state')
def instances_save_state(instance_id: str, body: dict | None = None) -> dict:
    """Pauses the attempt, closing the running stretch as one time entry."""
    body = body or {}
    idx = body.get('current_index')
    try:
        quiz_instance.save_state(
            instance_id, None if idx is None else int(idx))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _instance_detail(instance_id)


@app.post('/api/instances/{instance_id}/open')
def instances_open(instance_id: str) -> dict:
    """First time the quiz is actually opened: starts the clock."""
    try:
        quiz_instance.open_instance(instance_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _instance_detail(instance_id)


@app.post('/api/instances/{instance_id}/resume')
def instances_resume(instance_id: str) -> dict:
    """Restarts the clock on a paused attempt, keeping its position."""
    try:
        quiz_instance.resume_instance(instance_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _instance_detail(instance_id)


@app.post('/api/instances/{instance_id}/branch')
def instances_branch(instance_id: str) -> dict:
    """Forks the attempt: a clean slate from the same artifact, same content."""
    try:
        child = quiz_instance.branch_instance(instance_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _instance_detail(child['instance_id'])


@app.delete('/api/instances/{instance_id}')
def instances_delete(instance_id: str) -> dict:
    try:
        deleted = quiz_instance.delete_instance(instance_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail='instance not found')
    return {'deleted': True, 'instance_id': instance_id}


def _question_card(q) -> dict:
    """Serialize a GeneratedQuestion into the §7 question-card shape."""
    return {
        'number':          getattr(q, 'number', 0),
        'section':         getattr(q, 'section', ''),
        'q_type':          getattr(q, 'q_type', ''),
        'quiz_type':       getattr(q, 'quiz_type', '') or getattr(q, 'q_type', ''),
        'is_simulation':   getattr(q, 'is_simulation', False),
        'question_text':   normalize_ascii_math(getattr(q, 'question_text', '')),
'options':              [normalize_ascii_math(o) for o in (getattr(q, 'options', []) or [])],
        'correct_answer':       normalize_ascii_math(getattr(q, 'correct_answer', '')),
        'correct_option_index': getattr(q, 'correct_option_index', None),
        'option_rationales':    list(getattr(q, 'option_rationales', []) or []),
        'option_error_types':   list(getattr(q, 'option_error_types', []) or []),
        'sim_name':        getattr(q, 'sim_name', ''),
        'sim_instruction': normalize_ascii_math(getattr(q, 'sim_instruction', '')),
        'topic':           getattr(q, 'topic', ''),
        'pacing_stage':    getattr(q, 'pacing_stage', ''),
        'objective_type':  getattr(q, 'objective_type', ''),
        'position_rationale': getattr(q, 'position_rationale', ''),
        'source':          getattr(q, 'source', ''),
    }


@app.post('/api/quiz/chat')
def quiz_chat(body: dict) -> dict:
    """One pre-quiz chat turn. Returns the AI's text reply."""
    svc = _get_service()
    message  = str(body.get('message') or '')
    history  = body.get('history') or []   # [{role, content}] so far, not incl. message
    topic_files = svc.load_selected_topics()

    holder = {}

    def _res(text: str) -> None:
        holder['reply'] = normalize_ascii_math(text)
        holder['done'] = True

    def _err(msg: str) -> None:
        holder['error'] = msg
        holder['done'] = True

    svc.chat_message(message, history, topic_files, _res, _err)

    import time as _time
    deadline = _time.time() + 180
    while not holder.get('done') and _time.time() < deadline:
        _time.sleep(0.1)
    if holder.get('error'):
        raise HTTPException(status_code=500, detail=holder['error'])
    if 'reply' not in holder:
        raise HTTPException(status_code=504, detail='Chat timed out.')

    # ── Run extractor to update manifest ────────────────────────────────────
    from ..user_selections import load_manifest, merge_manifest, save_manifest, extract_manifest_diff
    from ..api_client import CLIBridgeClient

    try:
        current_manifest = load_manifest()
        turn_index = len(history) + 1
        # Build conversation text for the extractor (last few turns only to keep prompt small).
        conv_turns = (history or [])[-8:] + [{'role': 'user', 'content': message}, {'role': 'assistant', 'content': holder['reply']}]
        conv_text = json.dumps(conv_turns, indent=2)
        cli = CLIBridgeClient()
        diff = extract_manifest_diff(conv_text, current_manifest, cli, timeout=120.0)
        if isinstance(diff, dict):
            merged = merge_manifest(current_manifest, diff, turn_index=turn_index)
            save_manifest(merged)
            reply = {'reply': holder['reply'], 'selections': {k: v for k, v in merged.items() if not k.startswith('_')}}
        else:
            import sys
            print('preference-extractor: no usable diff from chat turn', file=sys.stderr)
            reply = {'reply': holder['reply']}
    except Exception as exc:
        import sys
        print(f'preference-extractor: failed after chat turn: {exc}', file=sys.stderr)
        reply = {'reply': holder['reply']}

    return reply


@app.post('/api/tutor/chat')
def tutor_chat(body: dict) -> dict:
    """One turn of a post-quiz tutoring thread about a completed question."""
    svc = _get_service()
    holder = {}

    def _res(text: str) -> None:
        holder['reply'] = text
        holder['done'] = True

    def _err(msg: str) -> None:
        holder['error'] = msg
        holder['done'] = True

    svc.tutor_message(
        question=str(body.get('question') or ''),
        user_answer=str(body.get('user_answer') or ''),
        correct_answer=str(body.get('correct_answer') or ''),
        follow_up=str(body.get('follow_up') or ''),
        history=body.get('history') or [],
        options=body.get('options'),
        on_result=_res,
        on_error=_err,
    )

    import time as _time
    deadline = _time.time() + 180
    while not holder.get('done') and _time.time() < deadline:
        _time.sleep(0.1)
    if holder.get('error'):
        raise HTTPException(status_code=500, detail=holder['error'])
    if 'reply' not in holder:
        raise HTTPException(status_code=504, detail='Tutoring timed out.')
    return {'reply': holder['reply']}


@app.post('/api/quiz/generate')
def quiz_generate(body: dict) -> dict:
    """Starts an async quiz-generation job and returns its id immediately."""
    svc = _get_service()
    user_request = str(body.get('user_request') or 'Generate a quiz')
    total = body.get('question_count')
    job = GenerationJob(
        service=svc,
        user_request=user_request,
        total_questions=int(total) if total else None,
        history=body.get('history') or [],
        prefs=body.get('prefs'),
    )
    job_id = uuid.uuid4().hex[:12]
    with _JOBS_LOCK:
        _JOBS[job_id] = job
    job.start()
    return {'job_id': job_id, 'state': 'running'}


@app.get('/api/quiz/job/{job_id}')
def quiz_job_status(job_id: str) -> dict:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail='job not found')
    snap = job.snapshot()
    payload = {
        'job_id': job_id,
        'state':  snap['state'],
        'stage':  snap['stage'],
        'detail': snap['detail'],
        'error':  snap['error'],
        'ready':  snap['ready'],
    }
    if snap['ready']:
        assert job.result is not None
        questions, meta = job.result
        from .. import quiz_note
        note = quiz_note.ensure_note(questions, meta)
        payload['quiz_id'] = note['quiz_id']
        payload['questions'] = [_question_card(q) for q in questions]
        payload['topics'] = meta.get('topics', [])
    return payload


@app.get('/api/quiz/last')
def quiz_last() -> dict:
    """Rebuilds the last successfully-completed quiz from the persisted
    sequence manifest. Returns the same shape as /api/quiz/job/{id} with
    questions, or 404 when there is no audit-passed run to resume."""
    from ..question_generator import build_questions_from_sequence
    from .. import quiz_note
    audit = config.get('compliance_audit', {})
    if not isinstance(audit, dict) or audit.get('audit_status') != 'PASSED':
        raise HTTPException(status_code=404, detail='No audit-passed quiz to resume.')
    seq = config.get('sequenced_quiz', {})
    if not isinstance(seq, dict) or not seq.get('ordered_quiz_sequence'):
        raise HTTPException(status_code=404, detail='No persisted quiz sequence to resume.')
    questions = build_questions_from_sequence(seq)
    topics = []
    for q in questions:
        if q.topic and q.topic not in topics:
            topics.append(q.topic)
    note = quiz_note.ensure_note(questions, {'topics': topics}, seq)
    return {
        'job_id': 'last',
        'quiz_id': note['quiz_id'],
        'state': 'done',
        'stage': 'done',
        'detail': 'Resumed from last persisted run.',
        'error': None,
        'ready': True,
        'questions': [_question_card(q) for q in questions],
        'topics': topics,
    }


@app.post('/api/quiz/complete')
def quiz_complete(body: dict) -> dict:
    """Marks + persists a finished quiz. Body:
    {'quiz_id'?, 'answers': [{number, user_choice, choice_meta, skipped}],
     'evaluation_on': bool, 'skip_mode'?, 'topics'?, 'mark_subjective'?,
     'instance_id'?}
    Grades MCQs locally, Hybrids via the strict marker (AI fallback), Theory via
    the parallel bucketed batches, and writes the History quiz log.

    'mark_subjective': False is the user's "Mark later" choice — History is
    written straight away with every subjective question (Hybrid and Theory)
    left pending. 'mark_theory' is accepted as a legacy alias for the same flag.
    'instance_id' links the finished attempt to the saved state it came from.
    """
    from .. import quiz_grader
    svc = _get_service()
    quiz_id = body.get('quiz_id') if isinstance(body.get('quiz_id'), str) else None
    answers = body.get('answers') or []
    evaluation_on = bool(body.get('evaluation_on', False))
    skip_mode = str(body.get('skip_mode') or 'zero')
    mark_flag = body.get('mark_subjective')
    if mark_flag is None:
        mark_flag = body.get('mark_theory', True)
    mark_subjective = bool(mark_flag)
    topics = body.get('topics')
    if not isinstance(topics, list) or not topics:
        topics = None
    try:
        res = quiz_grader.complete_quiz(
            svc, quiz_id, answers, evaluation_on,
            skip_mode=skip_mode, topics=topics, mark_subjective=mark_subjective)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    instance_id = body.get('instance_id')
    if isinstance(instance_id, str) and instance_id:
        try:
            quiz_instance.finish_instance(
                instance_id, res['history_quiz_id'],
                marking_pending=res.get('marking_pending', False))
        except ValueError:
            pass  # the quiz itself finished fine; only the link failed
    return res


@app.post('/api/quiz/mark-pending')
def quiz_mark_pending(body: dict) -> dict:
    """Grades a quiz the student deferred with "Mark later", then patches its
    existing History entry in place. Body: {'quiz_id'}"""
    from .. import quiz_grader
    svc = _get_service()
    quiz_id = str(body.get('quiz_id') or '')
    if not quiz_id:
        raise HTTPException(status_code=400, detail='quiz_id is required')
    try:
        return quiz_grader.mark_pending_quiz(svc, quiz_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get('/api/quiz/note/{quiz_id}')
def quiz_note_get(quiz_id: str) -> dict:
    """Full quiz note (metadata, answers, marks) + aggregate profile."""
    from .. import quiz_note as qn
    note = qn.load_note(quiz_id)
    if note is None:
        raise HTTPException(status_code=404, detail='Quiz note not found.')
    return {'note': note, 'profile': qn.score_profile(note, str(note.get('skip_mode') or 'zero'))}


@app.get('/api/quiz/note/{quiz_id}/cards')
def quiz_note_cards(quiz_id: str) -> dict:
    """The questions of a specific working note in the same card shape the
    quiz screen already renders, plus the answers recorded so far.

    This is how a saved state is reloaded: /api/quiz/last only rebuilds the
    most recent generated sequence, so it cannot serve an arbitrary note.
    """
    from .. import quiz_note as qn
    from ..question_generator import GeneratedQuestion
    note = qn.load_note(quiz_id)
    if note is None:
        raise HTTPException(status_code=404, detail='Quiz note not found.')
    questions = []
    for raw in note.get('questions') or []:
        if not isinstance(raw, dict):
            continue
        questions.append(_question_card(GeneratedQuestion(
            index=int(raw.get('index', 0) or 0),
            number=int(raw.get('number', 0) or 0),
            section=str(raw.get('section') or ''),
            q_type=str(raw.get('type') or raw.get('q_type') or ''),
            quiz_type=str(raw.get('type') or raw.get('q_type') or ''),
            is_simulation=bool(raw.get('is_simulation')),
            question_text=str(raw.get('question_text') or ''),
            options=list(raw.get('options') or []),
            correct_answer=str(raw.get('correct_answer') or ''),
            correct_option_index=qn._coerce_option_index(
                raw.get('correct_option_index')),
            option_rationales=list(raw.get('option_rationales') or []),
            option_error_types=list(raw.get('option_error_types') or []),
            sim_name=str(raw.get('sim_name') or ''),
            sim_instruction=str(raw.get('sim_instruction') or ''),
            topic=str(raw.get('topic') or ''),
            pacing_stage=str(raw.get('pacing_stage') or ''),
            objective_type=str(raw.get('objective_type') or ''),
            position_rationale=str(raw.get('position_rationale') or ''),
            source=str(raw.get('source') or ''),
        )))
    return {
        'quiz_id': quiz_id,
        'questions': questions,
        'topics': list(note.get('topics') or []),
        'subjects': list(note.get('subjects') or []),
        'evaluation_on': note.get('evaluation_on'),
        'skip_mode': note.get('skip_mode'),
    }


@app.get('/api/quiz/last/note')
def quiz_last_note() -> dict:
    """Quiz note for the last quiz built (current_quiz_id)."""
    from .. import quiz_note as qn
    current = config.get('current_quiz_id')
    if not isinstance(current, str) or not current:
        raise HTTPException(status_code=404, detail='No current quiz.')
    return quiz_note_get(current)


@app.post('/api/quiz/job/{job_id}/cancel')
def quiz_job_cancel(job_id: str) -> dict:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail='job not found')
    job.cancel()
    return {'job_id': job_id, 'state': 'cancelled'}


@app.post('/api/quiz/evaluate')
def quiz_evaluate(body: dict) -> dict:
    """Live evaluation of a single Section B (subjective) answer."""
    svc = _get_service()
    question       = str(body.get('question') or '')
    user_answer    = str(body.get('user_answer') or '')
    correct_answer = str(body.get('correct_answer') or '')

    holder = {}

    def _res(score: float, visible: str) -> None:
        holder['score'] = score
        holder['visible'] = visible
        holder['done'] = True

    def _err(msg: str) -> None:
        holder['error'] = msg
        holder['done'] = True

    svc.evaluate_live(question, user_answer, correct_answer, _res, _err)

    import time as _time
    deadline = _time.time() + 120
    while not holder.get('done') and _time.time() < deadline:
        _time.sleep(0.1)
    if holder.get('error'):
        raise HTTPException(status_code=500, detail=holder['error'])
    if 'score' not in holder:
        raise HTTPException(status_code=504, detail='Evaluation timed out.')
    return {'score': holder['score'], 'feedback': holder.get('visible', '')}


@app.post('/api/quiz/evaluate-batch')
def quiz_evaluate_batch(body: dict) -> dict:
    """End-of-quiz batch scoring of subjective answers."""
    svc = _get_service()
    groups = body.get('question_groups') or []
    holder = {}

    def _res(results) -> None:
        holder['results'] = [
            {'label': r.label, 'score': r.score, 'explanation': r.explanation}
            for r in results
        ]
        holder['done'] = True

    def _err(msg: str) -> None:
        holder['error'] = msg
        holder['done'] = True

    svc.evaluate_batch(groups, _res, _err)

    import time as _time
    deadline = _time.time() + 120
    while not holder.get('done') and _time.time() < deadline:
        _time.sleep(0.1)
    if holder.get('error'):
        raise HTTPException(status_code=500, detail=holder['error'])
    if 'results' not in holder:
        raise HTTPException(status_code=504, detail='Batch evaluation timed out.')
    return {'results': holder['results']}


def _deck_id(source: str, title: str) -> str:
    slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')[:60] or 'deck'
    return f"{source}:{slug}"


@app.get('/api/flashcards/decks')
def flashcards_decks() -> dict:
    topic_files = library_scanner.load_selected_topics(config.get_selected_topics())
    all_decks = flashcard_builder.build_all_decks(topic_files)
    quiz_decks, library_decks = [], []
    for d in all_decks:
        entry = {
            'id':      _deck_id(d.source, d.title),
            'title':   d.title,
            'subject': d.subject,
            'source':  d.source,
            'size':    d.size,
        }
        (quiz_decks if d.source == 'quiz' else library_decks).append(entry)
    return {'quiz_decks': quiz_decks, 'library_decks': library_decks}


@app.get('/api/flashcards/deck/{deck_id}')
def flashcards_deck(deck_id: str) -> dict:
    topic_files = library_scanner.load_selected_topics(config.get_selected_topics())
    for d in flashcard_builder.build_all_decks(topic_files):
        if _deck_id(d.source, d.title) == deck_id:
            return {'deck': {
                'id':      deck_id,
                'title':   d.title,
                'subject': d.subject,
                'source':  d.source,
                'size':    d.size,
                'cards':   [{
                    'front':   c.front,
                    'back':    c.back,
                    'topic':   c.topic,
                    'subject': c.subject,
                    'q_type':  c.q_type,
                    'source':  c.source,
                } for c in d.cards],
            }}
    raise HTTPException(status_code=404, detail='deck not found')


def _mask_keys(keys: list[str]) -> list[str]:
    return [MASKED_KEY if k else '' for k in keys]


def _apply_keys(stored: list[str], submitted: list[str]) -> list[str]:
    """Only overwrite submitted slots that are non-empty and not the mask."""
    out = list(stored)
    for i, val in enumerate(submitted):
        v = (val or '').strip()
        if not v or v == MASKED_KEY:
            continue
        if i < len(out):
            out[i] = v
        else:
            out.append(v)
    return out


@app.post('/api/library/scan')
def library_scan(body: dict) -> dict:
    root = str(body.get('root') or config.get_library_root() or '')
    try:
        tree = library_scanner.scan_library(root)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    subjects = []
    for sname in tree.subject_names():
        topics = []
        for tname in tree.topic_names(sname):
            t = tree.get_topic(sname, tname)
            if t is None:
                continue
            topics.append({
                'name':           t.name,
                'valid':          t.is_valid,
                'has_simulations': t.has_simulations,
                'folder_path':    str(t.folder_path),
            })
        subjects.append({'name': sname, 'topics': topics})
    return {
        'root':           str(tree.root_path),
        'subject_count':  len(subjects),
        'topic_count':    len(tree.all_topics()),
        'valid_count':    len(tree.valid_topics()),
        'subjects':       subjects,
    }


@app.get('/api/settings')
def settings_get() -> dict:
    return {
        'provider_mode':    config.get_provider_mode(),
        'cli_model':        config.get_cli_model(),
        'api': {
            'groq': {
                'keys':   _mask_keys(config.get_groq_keys()),
                'model':  config.get_groq_model(),
            },
            'openrouter': {
                'keys':   _mask_keys(config.get_openrouter_keys()),
                'model':  config.get_openrouter_model(),
            },
            'custom': {
                'url':   config.get_custom_api_url(),
                'key':   MASKED_KEY if config.get_custom_api_key() else '',
                'model': config.get_custom_model(),
            },
        },
        'library_root':     config.get_library_root(),
        'selected_topics':  config.get_selected_topics(),
        'question_types':   config.get_question_type_filters(),
        'sections':         config.get_question_section_preferences(),
        'shuffle':          config.get_shuffle_preferences(),
        'evaluation_on':    config.get_evaluation_on(),
        'last_skip_mode':   config.get_last_skip_mode(),
        'question_count':   config.get_question_count(),
    }


@app.post('/api/settings')
def settings_save(body: dict) -> dict:
    if 'provider_mode' in body:
        config.save_provider_mode(str(body['provider_mode']))
    if 'cli_model' in body:
        config.save_cli_model(str(body['cli_model']))
    if 'library_root' in body:
        config.save_library_root(str(body['library_root'] or ''))
    if 'selected_topics' in body:
        config.save_selected_topics(list(body['selected_topics']))

    api = body.get('api') or {}
    if 'groq' in api:
        g = api['groq']
        if 'model' in g:
            config.save_groq_model(str(g['model']))
        if 'keys' in g:
            config.save_groq_keys(_apply_keys(config.get_groq_keys(), g['keys']))
    if 'openrouter' in api:
        o = api['openrouter']
        if 'model' in o:
            config.save_openrouter_model(str(o['model']))
        if 'keys' in o:
            config.save_openrouter_keys(_apply_keys(config.get_openrouter_keys(), o['keys']))
    if 'custom' in api:
        c = api['custom']
        key = c.get('key', '')
        new_key = key if (key and key != MASKED_KEY) else config.get_custom_api_key()
        config.save_custom_provider(
            c.get('url', config.get_custom_api_url()),
            new_key,
            c.get('model', config.get_custom_model()),
        )

    if 'question_types' in body:
        qt = body['question_types']
        config.save_question_type_filters(
            bool(qt.get('mcq', True)),
            bool(qt.get('subj', True)),
            bool(qt.get('sim', True)),
        )
    if 'sections' in body:
        s = body['sections']
        config.save_question_section_preferences(
            bool(s.get('section_a_sim', True)),
            bool(s.get('section_a_nonsim', True)),
            bool(s.get('section_b_sim', True)),
            bool(s.get('section_b_nonsim', True)),
        )
    if 'shuffle' in body:
        sh = body['shuffle']
        config.save_shuffle_preferences(
            bool(sh.get('shuffle_enabled', False)),
            bool(sh.get('keep_sim_together', True)),
        )
    if 'evaluation_on' in body:
        config.save_evaluation_on(bool(body['evaluation_on']))
    if 'last_skip_mode' in body:
        config.save_last_skip_mode(str(body['last_skip_mode']))
    if 'question_count' in body:
        config.save_question_count(int(body['question_count']))

    _invalidate_service()
    return settings_get()


# ── Simulations ───────────────────────────────────────────────────────────────

class _SimLookupError(Exception):
    pass


def _resolve_sim_html(sim_name: str) -> tuple[Path, Path]:
    """
    Locates the folder for a simulation and returns (sim_folder, sim_html_path).

    Both AI-generated and user-downloaded prebuilt sims land in the same place:
    `<topic>/simulations/<sim_name>/sim.html` — so one code path finds both.

    `sim_name` may be a bare folder name, which is how older questions are
    stored, or a path relative to the library root
    (`subject/topic/simulations/name`). The path form is what disambiguates the
    same folder name appearing in more than one topic, which happens once a
    library holds a hundred simulations or more. A bare name that is unique
    still resolves, so existing questions keep working.

    Raises _SimLookupError with a friendly message when it cannot be resolved.
    """
    name = (sim_name or '').strip()
    root = config.get_library_root()
    if not root:
        raise _SimLookupError('Library root is not configured.')
    try:
        tree = library_scanner.scan_library(root)
    except FileNotFoundError:
        raise _SimLookupError(f'Library root not found: {root}') from None

    # Everything the scan found, as (folder, rel_path_from_root).
    found: list[tuple[Path, str]] = []
    root_path = Path(root).resolve()
    for subject, topic_map in tree.subjects.items():
        for topic_name, topic in topic_map.items():
            for sim in topic.simulations:
                rel = sim.folder_path.resolve().relative_to(root_path).as_posix()
                if not rel.startswith(f'{subject}/{topic_name}/'):
                    # Defensive: never hand out a path that repeats its segments.
                    rel = f'{subject}/{topic_name}/{sim.folder_path.name}'
                found.append((sim.folder_path, rel))

    # A path-form reference pins one exact folder. rel already ends with
    # `simulations/<name>`, so a caller supplying the full path and a caller
    # supplying only `<topic>/simulations/<name>` both land on the same entry.
    if '/' in name:
        want = name.strip('/').lower()
        matches = [f for f in found if f[1].lower() == want]
        if not matches:
            tail = want.rsplit('/simulations/', 1)[-1] if '/simulations/' in want else want
            matches = [f for f in found if f[0].name.lower() == tail]
        if not matches:
            raise _SimLookupError(f"No simulation at path '{name}' in the library.")
        candidates = [m[0] for m in matches]
    else:
        candidates = [f[0] for f in found if f[0].name.lower() == name.lower()]

    if not candidates:
        raise _SimLookupError(f"No simulation named '{name or '(empty)'}' found in the library.")
    if len(candidates) > 1:
        options = sorted(
            f[1] for f in found if f[0] in candidates)
        raise _SimLookupError(
            f"Simulation '{name}' exists in {len(candidates)} topics and cannot be "
            f"disambiguated by name. Use one of these paths: " + ', '.join(options)
        )

    folder = candidates[0]
    html = folder / 'sim.html'
    if not html.exists():
        raise _SimLookupError(
            f"Simulation '{name}' has no sim.html entry point. Found files: "
            + ', '.join(p.name for p in folder.iterdir() if p.is_file())
        )
    return folder, html


def _use_library_root(root: Path):
    """Points the sidecar at a library root, creating the config file if the
    real one does not exist yet. Never overwrites an existing setting."""
    if not config.get('library_root'):
        config.save_library_root(str(root))


def _sim_rel_folder(folder: Path) -> str:
    """The sim folder's path relative to the library root, e.g.
    'physics/Orbital Mechanics/simulations/orbital_mechanics_lab'."""
    root = Path(config.get_library_root()).resolve()
    try:
        return folder.resolve().relative_to(root).as_posix()
    except ValueError:
        return folder.name


@app.get('/api/sim/{sim_name:path}')
def sim_get(sim_name: str):
    """
    Serves the simulation's sim.html so the renderer can run it in an iframe.

    `sim_name` is either a bare folder name (when it is unique in the library) or
    a path relative to the library root, `<topic>/simulations/<sim_name>`, which
    is what disambiguates two simulations that share a folder name. An ambiguous
    bare name is a 404 listing every candidate path rather than a guess.

    The file on disk is never modified. The response gets a <base href> so
    relative asset paths resolve to /api/lib/…, and allowlisted CDN URLs are
    rewritten to the local dependency cache so the sim keeps working offline.
    """
    try:
        folder, html = _resolve_sim_html(sim_name)
    except _SimLookupError as exc:
        sim_assets.log(f'sim 404: {exc}')
        raise HTTPException(status_code=404, detail=str(exc))
    try:
        source = html.read_text(encoding='utf-8')
    except OSError as exc:
        sim_assets.log(f'sim unreadable: {html}: {exc}')
        raise HTTPException(status_code=500, detail=f'Could not read {html.name}: {exc}')
    served, _notes = sim_html.prepare(source, sim_html.base_href_for(_sim_rel_folder(folder)))
    return HTMLResponse(served, headers={
        'Content-Type': 'text/html; charset=utf-8',
        'Cache-Control': 'no-store',
        'X-Content-Type-Options': 'nosniff',
    })


def _safe_lib_path(rel: str) -> Path:
    """
    Resolves a /api/lib path to a real file, or raises HTTPException.

    Only two places are reachable: inside a simulation folder, and the shared
    X/vendor/ folder. The rest of the library — including every answer_bank.txt —
    is deliberately not servable, so a quiz's answer key cannot be read out of
    the sidecar by another process on the machine.
    """
    root = Path(config.get_library_root()).resolve()
    if not str(root):
        raise HTTPException(status_code=503, detail='Library root is not configured.')
    parts = [p for p in (rel or '').split('/') if p not in ('', '.')]
    if not parts or any(p == '..' for p in parts):
        raise HTTPException(status_code=400, detail='Invalid asset path.')

    candidate = (root / '/'.join(parts)).resolve()
    if not candidate.is_relative_to(root):
        raise HTTPException(status_code=403, detail='Asset path escapes the library.')

    # X/vendor/… is the shared library folder.
    vendor_root = (root / 'vendor').resolve()
    if candidate.is_relative_to(vendor_root):
        if not candidate.is_file():
            raise HTTPException(status_code=404, detail=f'Not found: {rel}')
        return candidate

    # Otherwise the path must sit inside a simulation folder, which the scanner
    # always places at <subject>/<topic>/simulations/<sim_name>/.
    if len(parts) >= 4 and parts[2] == 'simulations':
        sim_dir = (root / '/'.join(parts[:4])).resolve()
        if candidate.is_relative_to(sim_dir) and candidate.is_file():
            return candidate
        raise HTTPException(status_code=404, detail=f'Not found: {rel}')

    raise HTTPException(
        status_code=403,
        detail='Only files inside a simulations/ folder or X/vendor/ are served.')


@app.get('/api/lib/{rel:path}')
def sim_asset_get(rel: str):
    """Serves a simulation's own files, and shared libraries from X/vendor/."""
    path = _safe_lib_path(rel)
    try:
        body = path.read_bytes()
    except OSError as exc:
        sim_assets.log(f'asset 404: {rel}: {exc}')
        raise HTTPException(status_code=404, detail=f'Not found: {rel}')
    return Response(body, media_type=sim_assets.content_type_for(path.name), headers={
        # Content is immutable for a given path in practice; let the browser keep it.
        'Cache-Control': 'public, max-age=3600',
        'X-Content-Type-Options': 'nosniff',
    })


@app.get('/api/sim-cache/{url:path}')
def sim_cache_get(url: str, background: BackgroundTasks):
    """
    Serves a third-party dependency from the local cache.

    On the first run the file is downloaded and stored; on every run after that
    it is read from disk, so the simulation never needs the internet again. A
    revalidation runs in the background when the cached copy has gone stale, and
    is skipped entirely when offline.
    """
    if not url.startswith('https://'):
        raise HTTPException(status_code=400, detail='Cache keys must be https URLs.')
    try:
        body, meta = sim_assets.get(url)
    except sim_assets.SimAssetError as exc:
        sim_assets.log(f'dependency unavailable: {url}: {exc}')
        raise HTTPException(
            status_code=502,
            detail=(f'Could not obtain {url}. It is not in the local cache and could '
                    f'not be downloaded. Open the simulation once while online to '
                    f'cache it. ({exc})'))
    # Only a stale entry costs a network round trip; a fresh one never dials out.
    background.add_task(sim_assets.maybe_revalidate, url)
    return Response(body, media_type=meta.get('content_type') or 'application/octet-stream',
                    headers={
                        'Cache-Control': 'public, max-age=86400',
                        'X-Content-Type-Options': 'nosniff',
                    })


@app.get('/api/sim-cache-stats')
def sim_cache_stats():
    """Cache size and contents, for diagnostics."""
    return sim_assets.stats()


@app.delete('/api/sim-cache')
def sim_cache_clear():
    """Empties the dependency cache. Next run re-downloads what is needed."""
    removed = sim_assets.clear()
    sim_assets.log(f'cache cleared: {removed} entries removed')
    return {'removed': removed}
