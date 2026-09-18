"""
quiz_grader.py

End-to-end marking + persistence for a finished quiz (the "complete" flow).

Given the per-question answers from the renderer, this module:
  1. patches the student's choices into the master quiz note,
  2. marks every question (MCQ locally against the pre-declared answer,
     Hybrid via the strict marker with a deterministic fast path, Theory via
     the parallel bucketed batch grader),
  3. writes the QuizLog so the History screen (and dashboard) finally persist
     Electron-completed quizzes,
  4. returns the score profile + per-question verdicts for the report.

Flagged theory entries (no standard answer) and unanswered items are never
sent to a grader; they are recorded as ungraded/unanswered.
"""

from __future__ import annotations

import threading
import time
from typing import Optional

from . import config
from . import quiz_logger
from . import quiz_note
from . import theory_marker
from .hybrid_marker import hybrid_is_correct_strict


# ── Local MCQ option matching (mirrors the renderer's prefix heuristic) ───────

def _correct_option_index(options: list[str], correct_answer: str) -> Optional[int]:
    head = (correct_answer or '').strip().upper()[:1]
    if not head:
        return None
    for i, o in enumerate(options or []):
        if (o or '').strip().upper().startswith(head):
            return i
    return None


def _sel_from_choice(entry: dict) -> int:
    """Finds the option index from the free-text user_choice's leading letter."""
    choice = str(entry.get('user_choice') or '')
    head = choice.strip().upper()[:1]
    for i, o in enumerate(entry.get('options') or []):
        if (o or '').strip().upper().startswith(head):
            return i
    return -1


def _mark_mcq(note: dict, entry: dict) -> dict:
    quiz_id = note['quiz_id']
    number = int(entry['number'])
    correct_idx = _correct_option_index(entry.get('options') or [],
                                        entry.get('correct_answer', ''))
    if correct_idx is None:
        quiz_note.set_mark(quiz_id, number, None,
                           'ungraded — no standard answer', None, {})
        return {'number': number, 'score': None,
                'remark': 'ungraded — no standard answer', 'is_correct': None}

    meta = entry.get('choice_meta') or {}
    if meta.get('kind') == 'option' and meta.get('index') is not None:
        sel = int(meta['index'])
    else:
        sel = _sel_from_choice(entry)
    right = sel == correct_idx
    score = 1.0 if right else 0.0
    remark = 'right' if right else 'wrong'
    quiz_note.set_mark(quiz_id, number, score, remark, 'local', {})
    return {'number': number, 'score': score, 'remark': remark,
            'is_correct': right}


# ── Blocking wrapper around the evaluator callbacks ───────────────────────────

def _call_sync(trigger, timeout: float = 90.0) -> dict:
    """Runs `trigger(on_result, on_error)` and blocks until it settles."""
    holder: dict = {}
    done = threading.Event()

    def _res(*args):
        holder['ok'] = args[0] if args else None
        holder['extra'] = args[1:] if len(args) > 1 else None
        done.set()

    def _err(msg: str):
        holder['error'] = msg
        done.set()

    trigger(_res, _err)
    deadline = time.monotonic() + timeout
    while not done.is_set() and time.monotonic() < deadline:
        time.sleep(0.1)
    return holder


def _mark_hybrid(service, note: dict, entry: dict) -> dict:
    quiz_id = note['quiz_id']
    number = int(entry['number'])
    choice = str(entry.get('user_choice') or '').strip()
    correct = str(entry.get('correct_answer') or '').strip()
    if not correct:
        quiz_note.set_mark(quiz_id, number, None,
                           'ungraded — no standard answer', None, {})
        return {'number': number, 'score': None,
                'remark': 'ungraded — no standard answer', 'is_correct': None}
    if not choice:
        quiz_note.set_mark(quiz_id, number, None, 'unanswered', None, {})
        return {'number': number, 'score': None, 'remark': 'unanswered',
                'is_correct': None}

    if hybrid_is_correct_strict(choice, correct):
        quiz_note.set_mark(quiz_id, number, 1.0, 'right', 'hybrid_local', {})
        return {'number': number, 'score': 1.0, 'remark': 'right',
                'is_correct': True}

    holder = _call_sync(
        lambda res, err: service.evaluate_hybrid(
            question=str(entry.get('question_text', '')),
            user_answer=choice,
            correct_answer=correct,
            on_result=res,
            on_error=err,
        )
    )
    if holder.get('error') or 'ok' not in holder:
        quiz_note.set_mark(quiz_id, number, None,
                           'ungraded — evaluator failed', None, {})
        return {'number': number, 'score': None,
                'remark': 'ungraded — evaluator failed', 'is_correct': None}

    is_correct = bool(holder['ok'])
    explanation = (holder.get('extra') or [None])[0] or ''
    remark = 'right' if is_correct else 'wrong'
    score = 1.0 if is_correct else 0.0
    quiz_note.set_mark(quiz_id, number, score, remark, 'hybrid_ai',
                       {'note': explanation})
    return {'number': number, 'score': score, 'remark': remark,
            'is_correct': is_correct, 'note': explanation}


# ── Complete orchestrator ─────────────────────────────────────────────────────

def complete_quiz(service, quiz_id: Optional[str], answers: list[dict],
                  evaluation_on: bool, skip_mode: str = 'zero',
                  topics: Optional[list[str]] = None) -> dict:
    """
    Marks + persists a finished quiz and returns {quiz_id, profile, results,
    history_written}. `answers` is a list of {'number', 'user_choice',
    'choice_meta', 'skipped'} dicts matching the renderer's display order.
    """
    note = quiz_note.load_note(quiz_id) if isinstance(quiz_id, str) else None
    if note is None:
        current = config.get('current_quiz_id')
        note = quiz_note.load_note(current) if isinstance(current, str) else None
    if note is None:
        raise ValueError('No quiz note exists for this quiz. Build it first.')
    quiz_id = str(note['quiz_id'])

    quiz_note.set_run_options(quiz_id, evaluation_on, skip_mode)

    by_number = {}
    for ans in answers or []:
        number = int(ans.get('number', 0))
        choice = ans.get('user_choice')
        skipped = bool(ans.get('skipped')) and (choice is None or not str(choice).strip())
        quiz_note.set_user_choice(quiz_id, number, choice, ans.get('choice_meta'),
                                  skipped=skipped)
        by_number[number] = ans

    # Reload after patching — set_user_choice persists to disk, so the local
    # snapshot no longer reflects the student's answers.
    note = quiz_note.load_note(quiz_id)
    if note is None:
        raise RuntimeError(f'Quiz note vanished while completing {quiz_id!r}.')

    results: list[dict] = []
    for entry in note.get('questions', []):
        number = int(entry['number'])
        ans = by_number.get(number)
        choice = str(entry.get('user_choice') or '') if ans is not None else ''

        if entry.get('skipped'):
            quiz_note.set_mark(quiz_id, number, None, 'skipped', None, {})
            results.append({'number': number, 'score': None, 'remark': 'skipped',
                            'is_correct': None, 'skipped': True})
            continue
        if ans is None or not choice.strip():
            quiz_note.set_mark(quiz_id, number, None, 'unanswered', None, {})
            results.append({'number': number, 'score': None,
                            'remark': 'unanswered', 'is_correct': None})
            continue

        etype = entry.get('type', 'Theory')
        if etype == 'MCQ':
            results.append(_mark_mcq(note, entry))
        elif etype == 'Hybrid':
            results.append(_mark_hybrid(service, note, entry))
        else:  # Theory
            if not str(entry.get('correct_answer', '')).strip():
                desc = 'ungraded — no standard answer available'
                quiz_note.set_mark(quiz_id, number, None, desc, None, {})
                results.append({'number': number, 'score': None,
                                'remark': desc, 'is_correct': None})
            else:
                results.append({'number': number, 'score': None,
                                'remark': 'pending', 'is_correct': None})

    theory_verdicts = theory_marker.grade_theory(service, quiz_id)
    verdict_by_number = {v['number']: v for v in theory_verdicts}
    for r in results:
        v = verdict_by_number.get(r['number'])
        if not v:
            continue
        r['score'] = v['score']
        r['remark'] = v['remark']
        r['is_correct'] = bool(v['score'] == 1.0) if v['score'] is not None else None
        note_text = (v.get('eval_payload') or {}).get('note')
        if note_text:
            r['note'] = note_text

    fresh = quiz_note.load_note(quiz_id)
    if fresh is None:
        fresh = note  # theory verdicts already in the reloaded note
    _write_quiz_log(fresh, evaluation_on, skip_mode, topics)
    profile = quiz_note.score_profile(fresh, skip_mode)

    return {
        'quiz_id': quiz_id,
        'history_written': True,
        'profile': profile,
        'results': results,
    }


# ── QuizLog (History persistence) ─────────────────────────────────────────────

def _write_quiz_log(note: dict, evaluation_on: bool, skip_mode: str,
                    topics: Optional[list[str]]) -> str:
    topics = topics or note.get('topics') or []
    log = quiz_logger.new_quiz_log(
        topics=topics,
        evaluation_on=evaluation_on,
        skip_mode=skip_mode,
    )
    for e in note.get('questions', []):
        choice = str(e.get('user_choice') or '')
        if e.get('skipped'):
            choice = '(skipped)'
        etype = e.get('type', 'Theory')
        score = e.get('score')
        log.questions.append(quiz_logger.QuestionRecord(
            index=int(e.get('index', 0)),
            number=int(e.get('number', 1)),
            question=str(e.get('question_text', '')),
            section=e.get('section', 'B'),
            q_type=etype,
            is_simulation=bool(e.get('is_simulation', False)),
            correct_answer=str(e.get('correct_answer', '')),
            options=list(e.get('options') or []),
            user_answer=choice,
            is_correct=(bool(score == 1.0) if score is not None and etype in ('MCQ', 'Hybrid') else None),
            score=score if etype in ('Hybrid', 'Theory') else None,
            ai_feedback=str(e.get('remark') or '') if etype in ('Hybrid', 'Theory') else '',
            topic=str(e.get('topic', '')),
            sim_instruction=str(e.get('sim_instruction', '')),
            skipped=bool(e.get('skipped', False)),
        ))
    quiz_logger.save_quiz_log(log)
    quiz_logger.mark_complete(log)
    quiz_note.set_history_written(note['quiz_id'])
    return log.quiz_id