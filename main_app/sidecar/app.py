"""
sidecar/app.py

FastAPI sidecar served over localhost. Thin adapter — all logic lives in the
existing main_app modules; this layer only translates HTTP requests into those
calls and returns the JSON shapes documented in UI_UX_DESIGN_HANDOFF.md §7.
"""

import re
import threading
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .. import config
from .. import dashboard_stats
from .. import flashcard_builder
from .. import library_scanner
from .. import quiz_logger
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
        'questions': [{
            'number':         q.number,
            'question':       q.question,
            'options':        list(q.options or []),
            'section':        q.section,
            'q_type':         q.q_type,
            'is_simulation':  q.is_simulation,
            'topic':          q.topic,
            'user_answer':    q.user_answer,
            'correct_answer': q.correct_answer,
            'is_correct':     q.is_correct,
            'score':          q.score,
            'skipped':        q.skipped,
            'ai_feedback':    q.ai_feedback,
        } for q in log.questions],
    }


def _question_card(q) -> dict:
    """Serialize a GeneratedQuestion into the §7 question-card shape."""
    return {
        'number':          getattr(q, 'number', 0),
        'section':         getattr(q, 'section', ''),
        'q_type':          getattr(q, 'q_type', ''),
        'is_simulation':   getattr(q, 'is_simulation', False),
        'question_text':   getattr(q, 'question_text', ''),
        'options':         list(getattr(q, 'options', []) or []),
        'correct_answer':  getattr(q, 'correct_answer', ''),
        'sim_name':        getattr(q, 'sim_name', ''),
        'sim_instruction': getattr(q, 'sim_instruction', ''),
        'topic':           getattr(q, 'topic', ''),
        'pacing_stage':    getattr(q, 'pacing_stage', ''),
        'objective_type':  getattr(q, 'objective_type', ''),
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
        holder['reply'] = text
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
    return {'reply': holder['reply']}


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
        payload['questions'] = [_question_card(q) for q in questions]
        payload['topics'] = meta.get('topics', [])
    return payload


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
