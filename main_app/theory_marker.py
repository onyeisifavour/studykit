"""
theory_marker.py

Grades the Theory questions of a quiz from its minimal theory batch files
(≤ THEORY_BATCH_MAX questions each, possibly spanning several files). All
files are sent for grading at the same time (one thread per file), the raw
0–1 verdicts are snapped to THEORY_SCORE_LEVELS, and the results are written
back into both the batch file and the master quiz note.

Safety (from the theory-marking audit):
  - An entry with no standard answer (correct_answer_present is False) is
    flagged and NEVER sent to the grader — it stays ungraded in the note.
  - An unanswered entry (no user choice) is never graded either.
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional

from . import quiz_note
from . import score_parser


def eligible_entries(batch: dict) -> list[dict]:
    """
    Returns the grader-ready subset of a theory batch: entries that have a
    user answer AND a non-empty correct answer, reformatted for the prompt.
    """
    out: list[dict] = []
    for q in batch.get('questions', []):
        choice = q.get('user_choice')
        if choice is None or not str(choice).strip():
            continue
        if not q.get('correct_answer_present'):
            continue
        out.append({
            'label':          str(q.get('number', 0)),
            'question':       str(q.get('question_text', '')),
            'user_answer':    str(choice),
            'correct_answer': str(q.get('correct_answer', '')),
        })
    return out


def grade_theory(service, quiz_id: str,
                 on_batch: Optional[Callable[[int, int], None]] = None,
                 timeout: float = 180.0) -> list[dict]:
    """
    Grades every theory batch file for the quiz, in parallel. Returns a list
    of per-question verdict dicts:

        {'number': int, 'score': float | None, 'remark': str,
         'eval_source': str | None, 'eval_payload': dict}

    Results are written back via quiz_note.set_theory_mark as they land.
    Flagged entries are returned as 'ungraded' verdicts without any AI call.
    """
    quiz_note.write_theory_batches(load_note_checked(quiz_id))
    batches = quiz_note.load_theory_batches(quiz_id)
    n_batches = len(batches)
    verdicts: list[dict] = []
    lock = threading.Lock()

    def _verdict_from(number: int, score, remark: str,
                      source: Optional[str], payload: dict) -> None:
        v = {
            'number': number,
            'score': score,
            'remark': remark,
            'eval_source': source,
            'eval_payload': payload,
        }
        with lock:
            verdicts.append(v)
        quiz_note.set_theory_mark(quiz_id, number, score, remark, source, payload)

    def _grade_batch(index: int, batch: dict) -> None:
        entries = eligible_entries(batch)
        flagged = [q for q in batch.get('questions', [])
                   if q.get('user_choice') is not None and str(q.get('user_choice', '')).strip()
                   and not q.get('correct_answer_present')]
        for q in flagged:
            _verdict_from(int(q.get('number', 0)), None,
                          'ungraded — no standard answer available', None, {})
        if not entries:
            return
        if on_batch:
            on_batch(index, n_batches)
        holder: dict = {}
        done = threading.Event()

        def _res(results) -> None:
            holder['results'] = results
            done.set()

        def _err(msg: str) -> None:
            holder['error'] = msg
            done.set()

        service.evaluate_theory(entries, _res, _err)
        deadline = time.monotonic() + timeout
        while not done.is_set() and time.monotonic() < deadline:
            time.sleep(0.1)

        if holder.get('error') or 'results' not in holder:
            for e in entries:
                _verdict_from(int(e['label']), None,
                              'ungraded — evaluator failed', None, {})
            return

        by_label = {
            r.label.upper(): r for r in holder['results']
        }
        for e in entries:
            result = by_label.get(str(e['label']).upper())
            remark_text = 'Evaluation unavailable.'
            if result is not None:
                remark_text = result.explanation or remark_text
            # Snap raw → nearest credit level (bucketed theory scale).
            score = quiz_note.snap_score(result.score) if result is not None else None
            if score is None:
                _verdict_from(int(e['label']), None,
                              'ungraded — score unavailable', None, {})
                continue
            _verdict_from(int(e['label']), score, remark_text,
                          'theory_ai', {'raw_score': result.score if result is not None else None})

    threads = [
        threading.Thread(target=_grade_batch, args=(i, b), daemon=True)
        for i, b in enumerate(batches)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=timeout + 30)

    return verdicts


def load_note_checked(quiz_id: str) -> dict:
    note = quiz_note.load_note(quiz_id)
    if note is None:
        raise ValueError(f'No quiz note found for quiz_id={quiz_id!r}')
    return note