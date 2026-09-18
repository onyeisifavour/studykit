"""
quiz_note.py

Persists a rich per-quiz JSON "note" describing the quiz that was built, plus
minimal per-batch marking files for the theory questions.

Layout (stored on the local drive, next to the existing quiz logs):
    ~/.quiz_app/quizzes/<quiz_id>/quiz.json             — the master note
    ~/.quiz_app/quizzes/<quiz_id>/theory_batch_00.json  — ≤15 theory Q each
    ~/.quiz_app/quizzes/<quiz_id>/theory_batch_01.json  — may span files

The note is written at build time (once the Agent 4 / Agent 5 pipeline lands).
Every question carries its metadata (pacing stage, objective type, position
rationale, source), a correct_answer that is populated BEFORE the quiz for
MCQs, Hybrids, bank theories and pre-declared sim answers, and a per-question
marking block (score / remark / eval).

Marking semantics (see docs/quiz-note-and-grading.md):
    MCQ / Hybrid            → right / wrong (0 / 1)
    Theory                  → discrete 5-level rubric: 0 / 0.25 / 0.5 / 0.75 / 1
    eval                    → null until a marking mechanism runs; then
                              {'source', 'score', 'note', 'triggered_at'}
    correct_answer_present  → False flags a theory question that must never be
                              sent to the grader (missing standard answer).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from . import config

# Five-level theory marking rubric (user-specified, 2026-09-11). The grader
# produces one of these levels directly; snap_score is a defensive pass-through
# for stray values. Levels must stay in sync with the rubric in THEORY_EVAL_SYSTEM.
THEORY_SCORE_LEVELS = (0.0, 0.25, 0.5, 0.75, 1.0)  # full = 100%, quarter = 25%
THEORY_BATCH_MAX = 15

QUIZ_NOTES_DIR = Path.home() / '.quiz_app' / 'quizzes'


# ── Path / id helpers ─────────────────────────────────────────────────────────

def note_dir(quiz_id: str) -> Path:
    return QUIZ_NOTES_DIR / quiz_id


def note_path(quiz_id: str) -> Path:
    return note_dir(quiz_id) / 'quiz.json'


def theory_batch_path(quiz_id: str, batch_index: int) -> Path:
    return note_dir(quiz_id) / f'theory_batch_{batch_index:02d}.json'


def quiz_id_from_manifest(sequence_manifest: Optional[dict]) -> str:
    """Deterministic id from the quiz content, stable across /api/quiz/last."""
    seq = (sequence_manifest or {}).get('ordered_quiz_sequence', [])
    if not seq:
        return ''
    try:
        payload = json.dumps(seq, sort_keys=True, ensure_ascii=False).encode('utf-8')
    except Exception:
        return ''
    return hashlib.sha1(payload).hexdigest()[:12]


def _questions_sig(questions: list) -> str:
    parts = [(
        getattr(q, 'number', 0),
        getattr(q, 'quiz_type', '') or getattr(q, 'q_type', ''),
        str(getattr(q, 'question_text', '')),
        str(getattr(q, 'correct_answer', '')),
        list(getattr(q, 'options', []) or []),
    ) for q in questions]
    raw = json.dumps(parts, sort_keys=True, ensure_ascii=False).encode('utf-8')
    return hashlib.sha1(raw).hexdigest()[:16]


def snap_score(raw: float) -> float:
    """Snaps a raw 0–1 score to the nearest THEORY_SCORE_LEVELS bucket."""
    raw = max(0.0, min(1.0, float(raw or 0.0)))
    return min(THEORY_SCORE_LEVELS, key=lambda level: abs(level - raw))


def _now() -> str:
    return datetime.now().isoformat()


# ── Note building ─────────────────────────────────────────────────────────────

def _canonical_type(q) -> str:
    """Canonical quiz type: 'MCQ' | 'Hybrid' | 'Theory'."""
    qt = getattr(q, 'quiz_type', '') or ''
    if qt in ('MCQ', 'Hybrid', 'Theory'):
        return qt
    return 'MCQ' if getattr(q, 'q_type', '') == 'MCQ' else 'Theory'


def _entry_from_question(q) -> dict:
    correct = str(getattr(q, 'correct_answer', '') or '').strip()
    return {
        'index':                 int(getattr(q, 'index', 0)),
        'number':                int(getattr(q, 'number', 1)),
        'section':               str(getattr(q, 'section', '')) or 'B',
        'type':                  _canonical_type(q),
        'format':                'Sim' if getattr(q, 'is_simulation', False) else 'Non-Sim',
        'is_simulation':         bool(getattr(q, 'is_simulation', False)),
        'topic':                 str(getattr(q, 'topic', '') or ''),
        'subject':               str(getattr(q, 'subject', '') or ''),
        'objective_type':        str(getattr(q, 'objective_type', '') or ''),
        'pacing_stage':          str(getattr(q, 'pacing_stage', '') or ''),
        'position_rationale':    str(getattr(q, 'position_rationale', '') or ''),
        'source':                str(getattr(q, 'source', '') or ''),
        'question_text':         str(getattr(q, 'question_text', '') or ''),
        'options':               list(getattr(q, 'options', []) or []),
        'sim_name':              str(getattr(q, 'sim_name', '') or ''),
        'sim_instruction':       str(getattr(q, 'sim_instruction', '') or ''),
        'correct_answer':        correct,
        'correct_answer_present': bool(correct),
        'user_choice':           None,
        'choice_meta':           None,
        'skipped':               False,
        'score':                 None,
        'remark':                None,
        'eval':                  None,
    }


def _sequence_metadata(sequence_manifest: dict) -> dict:
    meta = (sequence_manifest or {}).get('sequence_metadata') or {}
    return {
        'total_questions':  meta.get('total_questions'),
        'pacing_strategy':  str(meta.get('pacing_strategy', '') or ''),
        'target_cognitive_flow': str(meta.get('target_cognitive_flow', '') or ''),
    }


def _note_from_questions(quiz_id: str, questions: list, sequence_manifest: dict, meta: dict) -> dict:
    topics:   list[str] = []
    subjects: list[str] = []
    for q in questions:
        t = str(getattr(q, 'topic', '') or '')
        if t and t not in topics:
            topics.append(t)
        s = str(getattr(q, 'subject', '') or '')
        if s and s not in subjects:
            subjects.append(s)
    return {
        'quiz_id':            quiz_id,
        'content_sig':        _questions_sig(questions),
        'created_at':         _now(),
        'updated_at':         _now(),
        'topics':             topics,
        'subjects':           subjects,
        'total_questions':    len(questions),
        'evaluation_on':      None,
        'skip_mode':          None,
        'sequence_metadata':  _sequence_metadata(sequence_manifest),
        'history_written':    False,
        'meta':               meta or {},
        'questions':          [_entry_from_question(q) for q in questions],
    }


def load_note(quiz_id: str) -> Optional[dict]:
    path = note_path(quiz_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return None


def save_note(note: dict) -> None:
    note['updated_at'] = _now()
    note_dir(note['quiz_id']).mkdir(parents=True, exist_ok=True)
    note_path(note['quiz_id']).write_text(
        json.dumps(note, indent=2, ensure_ascii=False), encoding='utf-8')


def ensure_note(questions: list, meta: Optional[dict] = None,
                sequence_manifest: Optional[dict] = None) -> dict:
    """
    Returns the note for this quiz, creating it from the assembled questions
    on first sight. The note is reused when the quiz content signature matches
    (same build or a resume of the last persisted run), so user answers and
    marks survive rebuilds of the identical quiz.
    """
    if not questions:
        raise ValueError('ensure_note requires at least one question')
    sig = _questions_sig(questions)

    current = config.get('current_quiz_id')
    rec = load_note(current) if current else None
    if rec is not None and rec.get('content_sig') == sig:
        return rec

    quiz_id = ''
    if (sequence_manifest or {}).get('ordered_quiz_sequence'):
        quiz_id = quiz_id_from_manifest(sequence_manifest)
    if quiz_id:
        rec = load_note(quiz_id)
        if rec is not None:
            if rec.get('content_sig') == sig:
                return rec
            quiz_id = sig[:12]  # stale manifest id collision — scope uniquely
    else:
        quiz_id = sig[:12]

    note = _note_from_questions(quiz_id, questions, sequence_manifest or {}, meta or {})
    save_note(note)
    write_theory_batches(note)
    config.set_value('current_quiz_id', quiz_id)
    return note


# ── Per-question patches ──────────────────────────────────────────────────────

def _find_entry(note: dict, number: int) -> Optional[dict]:
    for e in note.get('questions', []):
        if int(e.get('number', -1)) == int(number):
            return e
    return None


def set_user_choice(quiz_id: str, number: int, user_choice: Any,
                    choice_meta: Optional[dict] = None,
                    skipped: bool = False) -> dict:
    """Records the student's selection on a question. Returns the note."""
    note = load_note(quiz_id) or {}
    entry = _find_entry(note, number)
    if entry is None:
        return note
    entry['user_choice'] = user_choice
    if choice_meta is not None:
        entry['choice_meta'] = choice_meta
    if skipped:
        entry['skipped'] = True
    elif 'skipped' in entry:
        # A real (re)attempt supersedes any earlier 'skipped' flag, e.g. from a
        # previous completion pass. Stale flags would otherwise mark a question
        # skipped forever even when the student answered it this time.
        del entry['skipped']
    save_note(note)
    return note


def set_mark(quiz_id: str, number: int, score: Optional[float], remark: str,
             eval_source: Optional[str], eval_payload: dict) -> dict:
    """Writes a completed marking verdict for one question. Returns the note."""
    note = load_note(quiz_id) or {}
    entry = _find_entry(note, number)
    if entry is None:
        return note
    entry['score'] = float(score) if score is not None else None
    entry['remark'] = remark
    entry['eval'] = None
    if eval_source:
        verdict = {
            'source': eval_source,
            'score': entry['score'],
            'note': remark,
            'triggered_at': _now(),
        }
        if isinstance(eval_payload, dict):
            verdict.update(eval_payload)
        entry['eval'] = verdict
    save_note(note)
    return note


def set_history_written(quiz_id: str) -> None:
    note = load_note(quiz_id)
    if note is None:
        return
    note['history_written'] = True
    save_note(note)


def set_run_options(quiz_id: str, evaluation_on: bool, skip_mode: str) -> None:
    note = load_note(quiz_id)
    if note is None:
        return
    note['evaluation_on'] = evaluation_on
    note['skip_mode'] = skip_mode
    save_note(note)


# ── Theory batch files (minimal marking data, ≤ THEORY_BATCH_MAX questions) ───

def _theory_entries(note: dict) -> list[dict]:
    out = []
    for e in note.get('questions', []):
        if e.get('type') == 'Theory':
            entry = {'number': int(e.get('number', 0))}
            entry.update(e)
            out.append(entry)
    return out


def write_theory_batches(note: dict) -> list[Path]:
    """
    (Re)writes the minimal theory batch files for the note. Each file holds at
    most THEORY_BATCH_MAX questions and only the data the grader needs.
    """
    quiz_id = note['quiz_id']
    note_dir(quiz_id).mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    entries = _theory_entries(note)
    for batch_index in range(0, len(entries), THEORY_BATCH_MAX):
        chunk = entries[batch_index: batch_index + THEORY_BATCH_MAX]
        data = {
            'quiz_id': quiz_id,
            'batch_index': batch_index // THEORY_BATCH_MAX,
            'max_capacity': THEORY_BATCH_MAX,
            'questions': [{
                'number': e['number'],
                'question_text': e['question_text'],
                'user_choice': e.get('user_choice'),
                'correct_answer': e.get('correct_answer', ''),
                'correct_answer_present': bool(e.get('correct_answer', '').strip()),
                'mark': {
                    'score': e.get('score'),
                    'remark': e.get('remark'),
                },
            } for e in chunk],
        }
        path = theory_batch_path(quiz_id, batch_index // THEORY_BATCH_MAX)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
        paths.append(path)
    return paths


def load_theory_batches(quiz_id: str) -> list[dict]:
    out = []
    batch_index = 0
    while True:
        path = theory_batch_path(quiz_id, batch_index)
        if not path.exists():
            break
        try:
            out.append(json.loads(path.read_text(encoding='utf-8')))
        except Exception:
            pass
        batch_index += 1
    return out


def set_theory_mark(quiz_id: str, number: int, score: Optional[float],
                    remark: str, eval_source: Optional[str], eval_payload: dict) -> None:
    """Sets a theory verdict both in the batch file and the master note."""
    set_mark(quiz_id, number, score, remark, eval_source, eval_payload)
    for batch in load_theory_batches(quiz_id):
        for q in batch.get('questions', []):
            if int(q.get('number', -1)) == int(number):
                q['mark'] = {
                    'score': float(score) if score is not None else None,
                    'remark': remark,
                }
                theory_batch_path(quiz_id, int(batch['batch_index'])).write_text(
                    json.dumps(batch, indent=2, ensure_ascii=False), encoding='utf-8')
                return


# ── Score profile ─────────────────────────────────────────────────────────────

def _credit(entry: dict, skip_mode: str) -> Optional[float]:
    """
    Per-question credit toward the profile:
      - skipped:    0.0 under 'zero', omitted under 'exclude'
      - unanswered: omitted (never attempted — no credit either way)
      - graded:     entry.score (0/1 for MCQ/Hybrid, bucketed 0–1 for Theory)
    """
    if entry.get('skipped'):
        return 0.0 if skip_mode == 'zero' else None
    if entry.get('score') is None:
        return None
    return float(entry['score'])


def score_profile(note: dict, skip_mode: str = 'zero') -> dict:
    """
    Builds the aggregate profile from the note's per-question marks. Each
    attempted question counts once (sole or sub-question); right MCQ/Hybrid
    = 1/1; theory uses the fluid 0–1 credit.
    """
    counts = {'total': 0, 'attempted': 0, 'marked': 0,
              'skipped': 0, 'unanswered': 0, 'ungraded': 0}
    by_type: dict[str, dict] = {}
    by_stage: dict[str, dict] = {}
    by_topic: dict[str, dict] = {}
    earned = 0.0

    for e in note.get('questions', []):
        counts['total'] += 1
        qtype = e.get('type', 'Theory')
        tp = by_type.setdefault(qtype, {'earned': 0.0, 'count': 0, 'correct': 0})
        st = by_stage.setdefault(e.get('pacing_stage') or '—', {'earned': 0.0, 'count': 0})
        to = by_topic.setdefault(e.get('topic') or '—', {'earned': 0.0, 'count': 0})
        for bucket in (tp, st, to):
            bucket['count'] += 1

        if e.get('skipped'):
            counts['skipped'] += 1
            credit = 0.0 if skip_mode == 'zero' else None
        elif e.get('user_choice') is None and e.get('score') is None:
            counts['unanswered'] += 1
            credit = None
        elif e.get('score') is None:
            counts['ungraded'] += 1
            credit = None
        else:
            counts['marked'] += 1
            credit = float(e['score'])

        if credit is not None:
            counts['attempted'] += 1
            earned += credit
            for bucket in (tp, st, to):
                bucket['earned'] += credit
            if qtype in ('MCQ', 'Hybrid') and credit == 1.0:
                tp['correct'] += 1

    overall = round((earned / counts['attempted']) * 100, 1) if counts['attempted'] else None
    return {
        'total': counts['total'],
        'attempted': counts['attempted'],
        'marked': counts['marked'],
        'skipped': counts['skipped'],
        'unanswered': counts['unanswered'],
        'ungraded': counts['ungraded'],
        'earned': round(earned, 4),
        'overall': overall,
        'by_type': by_type,
        'by_pacing_stage': by_stage,
        'by_topic': by_topic,
    }