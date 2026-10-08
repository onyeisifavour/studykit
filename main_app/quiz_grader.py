"""
quiz_grader.py

End-to-end marking + persistence for a finished quiz (the "complete" flow).

Given the per-question answers from the renderer, this module:
  1. patches the student's choices into the master quiz note,
  2. marks every question (MCQ locally against the pre-declared answer;
     Theory and Hybrid together through the parallel batch grader, which snaps
     Hybrid to strict binary credit and Theory to the five-level scale — a
     Hybrid exact match is settled locally first and costs no API call),
  3. writes the QuizLog so the History screen (and dashboard) finally persist
     Electron-completed quizzes,
  4. returns the score profile + per-question verdicts for the report.

Flagged theory entries (no standard answer) and unanswered items are never
sent to a grader; they are recorded as ungraded/unanswered.
"""

from __future__ import annotations

from typing import Optional

from . import config
from . import quiz_logger
from . import quiz_note
from . import theory_marker
from .hybrid_marker import hybrid_exact_match


# ── Local MCQ option matching (mirrors the renderer's prefix heuristic) ───────

# Sentinel remark for a subjective question deferred by "Mark later". It is
# persisted in the working note but never surfaced as feedback text.
PENDING_REMARK = 'pending'

def _correct_option_index(options: list[str], correct_answer: str,
                          correct_option_index: Optional[int] = None) -> Optional[int]:
    """
    Locates the correct option.

    Prefers the explicit `correct_option_index` when present and in range.
    Options are display text and may reword the correct answer, so text/letter
    matching is only a fallback for bank-copied questions and older manifests
    that carry no index.
    """
    if isinstance(correct_option_index, int) and not isinstance(correct_option_index, bool):
        if 0 <= correct_option_index < len(options or []):
            return correct_option_index
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


def _feedback_text(entry: dict) -> str:
    """The remark as user-facing feedback, minus the pending sentinel.

    A deferred subjective question carries PENDING_REMARK in the note so the
    attempt knows it still owes a mark. That is state, not feedback, so the
    History entry leaves the field empty and the UI shows its pending badge.
    """
    remark = str(entry.get('remark') or '')
    return '' if remark == PENDING_REMARK else remark


def _defer_subjective(note: dict, entry: dict) -> dict:
    """Leave a subjective question (Hybrid or Theory) pending a later pass.

    The mark is persisted as PENDING_REMARK rather than simply omitted, so the
    note on disk matches the History entry and a resumed attempt shows the
    question as still awaiting marking. That sentinel is stripped again when
    the History log is written — the UI carries a pending badge instead of
    showing the word as if it were feedback.
    """
    quiz_id = note['quiz_id']
    number = int(entry['number'])
    quiz_note.set_mark(quiz_id, number, None, PENDING_REMARK, None, {})
    return {'number': number, 'score': None, 'remark': PENDING_REMARK,
            'is_correct': None}


def _mark_mcq(note: dict, entry: dict) -> dict:
    quiz_id = note['quiz_id']
    number = int(entry['number'])
    correct_idx = _correct_option_index(entry.get('options') or [],
                                        entry.get('correct_answer', ''),
                                        entry.get('correct_option_index'))
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


# ── Complete orchestrator ─────────────────────────────────────────────────────

def complete_quiz(service, quiz_id: Optional[str], answers: list[dict],
                  evaluation_on: bool, skip_mode: str = 'zero',
                  topics: Optional[list[str]] = None,
                  mark_subjective: bool = True) -> dict:
    """
    Marks + persists a finished quiz and returns {quiz_id, profile, results,
    history_written, marking_pending}. `answers` is a list of {'number',
    'user_choice', 'choice_meta', 'skipped'} dicts matching the renderer's
    display order.

    `mark_subjective=False` is the "Mark later" choice: MCQs are still marked
    and the History entry is written immediately, but every subjective
    question — Hybrid and Theory alike — is left pending for a later pass. The
    entry is flagged `marking_pending` so the UI can say so rather than showing
    a blank score.

    A Hybrid answer the deterministic matcher settles exactly is marked here for
    free; every other subjective question is deferred to the batched marker,
    which snaps Hybrid to strict binary credit and Theory to the five-level
    scale. That keeps the whole subjective tail on one code path.
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
            # An exact match is settled locally and for free — but only on a
            # "Mark now" finish, since "Mark later" must defer the whole
            # subjective tail so History lands with every subjective score null.
            # A non-match is never a verdict: it goes to the batched evaluator,
            # which judges whether the answer is *right* (equivalent wording and
            # notation count) and then snaps that to binary credit.
            exact = hybrid_exact_match(
                str(entry.get('user_choice') or '').strip(),
                str(entry.get('correct_answer') or '').strip(),
            )
            if mark_subjective and exact:
                quiz_note.set_mark(quiz_id, number, 1.0, 'right', 'hybrid_local', {})
                results.append({'number': number, 'score': 1.0, 'remark': 'right',
                                'is_correct': True})
            else:
                # Graded by theory_marker in the same batch as Theory, so a
                # Hybrid costs one shared API call rather than its own.
                results.append(_defer_subjective(note, entry))
        else:  # Theory
            if not str(entry.get('correct_answer', '')).strip():
                desc = 'ungraded — no standard answer available'
                quiz_note.set_mark(quiz_id, number, None, desc, None, {})
                results.append({'number': number, 'score': None,
                                'remark': desc, 'is_correct': None})
            else:
                results.append(_defer_subjective(note, entry))

    if mark_subjective:
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
    history_quiz_id = _write_quiz_log(fresh, evaluation_on, skip_mode, topics,
                                      marking_pending=not mark_subjective)
    profile = quiz_note.score_profile(fresh, skip_mode)

    return {
        'quiz_id': quiz_id,
        'history_written': True,
        'history_quiz_id': history_quiz_id,
        'marking_pending': not mark_subjective,
        'profile': profile,
        'results': results,
    }


def mark_pending_quiz(service, quiz_id: str) -> dict:
    """
    Second half of "Mark later": grades every deferred subjective question for a
    quiz that already has a History entry, then patches that entry in place.

    Theory and Hybrid both go through the parallel batched marker — Hybrid is
    snapped to strict binary credit on the way out, Theory to the five-level
    scale — so a "Mark later" quiz and a "Mark now" finish reach identical
    verdicts by the same route.

    Safe to call more than once — the graders rebuild from the working note, so
    a retry re-marks from the source of truth rather than compounding the
    previous pass.
    """
    log = quiz_logger.load_quiz_log(quiz_id)
    if log is None:
        raise ValueError(f'No such quiz log: {quiz_id!r}')
    # An instance logs under a fresh timestamp id while its working note keeps
    # its own work id, so the log records which note it came from.
    work_quiz_id = str(log.source_quiz_id or quiz_id)
    note = quiz_note.load_note(work_quiz_id)
    if note is None:
        raise ValueError(f'No working note for quiz {quiz_id!r}; nothing to mark.')

    # Snapshot which subjective questions are genuinely still pending *before*
    # grading. grade_theory writes its verdicts straight into the note, so
    # asking afterwards would see every question as already marked and skip
    # the lot.
    pending_numbers = {
        int(e['number']) for e in (note.get('questions') or [])
        if e.get('type') in ('Theory', 'Hybrid')
        and not e.get('skipped') and e.get('score') is None
    }

    verdicts = theory_marker.grade_theory(service, work_quiz_id)
    by_number = {int(v['number']): v for v in verdicts}

    fresh = quiz_note.load_note(work_quiz_id) or note
    results = []
    for e in fresh.get('questions', []):
        etype = e.get('type', 'Theory')
        if etype not in ('Theory', 'Hybrid'):
            continue
        number = int(e.get('number', 0))
        # Only re-grade what was still pending when this pass started.
        if number not in pending_numbers:
            continue
        v = by_number.get(number)
        if not v:
            continue
        results.append({
            'number':     number,
            'score':      v.get('score'),
            'remark':     v.get('remark'),
            'is_correct': bool(v.get('score') == 1.0) if v.get('score') is not None else None,
            'note':       (v.get('eval_payload') or {}).get('note'),
        })

    # Patch the already-written History entry: subjective scores and feedback
    # only. MCQ verdicts recorded at finish time are left exactly as they were.
    for r in results:
        for q in log.questions:
            if int(q.number) != r['number']:
                continue
            q.score = r['score']
            q.ai_feedback = str(r.get('remark') or '') or q.ai_feedback
            # Only Hybrid carries a boolean right/wrong. Theory is fluid 0-1
            # credit, so its is_correct stays None by design and must not be
            # back-filled from a full-credit score.
            if q.q_type == 'Hybrid' and r.get('is_correct') is not None:
                q.is_correct = bool(r['is_correct'])
            break
    log.marking_pending = False
    quiz_logger.save_quiz_log(log)

    # The saved state this attempt came from carries the same pending flag, so
    # clear it too — otherwise Artifacts → Saved States would keep offering
    # "Mark now" for an entry that is already marked.
    from . import quiz_instance
    instance_id = quiz_instance.find_by_history_id(str(quiz_id))
    if instance_id:
        try:
            quiz_instance.mark_pending_cleared(instance_id)
        except Exception:
            pass

    return {
        'quiz_id':          str(quiz_id),
        'marking_pending':  False,
        'marked':           len(results),
        'results':          results,
        'profile':          quiz_note.score_profile(fresh, log.skip_mode),
    }


# ── QuizLog (History persistence) ─────────────────────────────────────────────

def _write_quiz_log(note: dict, evaluation_on: bool, skip_mode: str,
                    topics: Optional[list[str]],
                    marking_pending: bool = False) -> str:
    topics = topics or note.get('topics') or []
    log = quiz_logger.new_quiz_log(
        topics=topics,
        evaluation_on=evaluation_on,
        skip_mode=skip_mode,
    )
    log.marking_pending = bool(marking_pending)
    log.source_quiz_id = str(note.get('quiz_id') or '') or None
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
            correct_option_index=e.get('correct_option_index'),
            option_rationales=list(e.get('option_rationales') or []),
            option_error_types=list(e.get('option_error_types') or []),
            user_answer=choice,
            is_correct=(bool(score == 1.0) if score is not None and etype in ('MCQ', 'Hybrid') else None),
            score=score if etype in ('Hybrid', 'Theory') else None,
            ai_feedback=_feedback_text(e) if etype in ('Hybrid', 'Theory') else '',
            topic=str(e.get('topic', '')),
            sim_instruction=str(e.get('sim_instruction', '')),
            skipped=bool(e.get('skipped', False)),
        ))
    quiz_logger.save_quiz_log(log)
    quiz_logger.mark_complete(log)
    quiz_note.set_history_written(note['quiz_id'])
    return log.quiz_id