"""Tests the "Mark later" split: History lands immediately, the whole
subjective tail (Hybrid + Theory) grades later."""

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_TMP = Path(tempfile.mkdtemp(prefix='quiz-marktest-'))
os.environ['HOME'] = str(_TMP)
os.environ['XDG_CONFIG_HOME'] = str(_TMP / '.config')

for _m in [m for m in list(sys.modules) if m.startswith('main_app')]:
    del sys.modules[_m]

from main_app import hybrid_marker, prompts, quiz_grader, quiz_logger, quiz_note

PASS, FAIL = 0, 0


def check(label, cond, extra=''):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f'PASS {label}')
    else:
        FAIL += 1
        print(f'FAIL {label} {extra}')


class FakeTheoryResult:
    """Mirrors the result object theory_marker reads (.label/.score/.explanation)."""

    def __init__(self, label, score, explanation):
        self.label = label
        self.score = score
        self.explanation = explanation


class FakeService:
    """Stands in for QuizService. Records every batch it is handed.

    `partial` is the raw 0-1 score it reports back for every question, so a
    test can prove Hybrid rounds a near-miss down to zero while Theory keeps
    its partial credit.
    """

    def __init__(self, partial=1.0):
        self.batches = []
        self.hybrid_calls = []
        self.partial = partial

    def evaluate_theory(self, entries, on_result, on_error):
        self.batches.append(entries)
        on_result([FakeTheoryResult(e['label'], self.partial, 'good')
                   for e in (entries or [])])

    def evaluate_hybrid(self, question, user_answer, correct_answer,
                        on_result, on_error):
        self.hybrid_calls.append(user_answer)
        on_result(user_answer.strip() == correct_answer.strip(), 'hybrid note')


def make_note(quiz_id):
    note = {
        'quiz_id': quiz_id, 'content_sig': 'sig', 'created_at': 'now',
        'updated_at': 'now', 'topics': ['T'], 'subjects': ['Physics'],
        'total_questions': 5, 'evaluation_on': None, 'skip_mode': None,
        'sequence_metadata': {}, 'history_written': False, 'meta': {},
        'questions': [
            {'index': 0, 'number': 1, 'section': 'A', 'type': 'MCQ',
             'question_text': 'mcq one', 'options': ['A. a', 'B. b'],
             'correct_answer': 'A', 'topic': 'T', 'is_simulation': False,
             'user_choice': None, 'skipped': False, 'score': None, 'remark': None},
            {'index': 1, 'number': 2, 'section': 'B', 'type': 'Theory',
             'question_text': 'theory two', 'options': [],
             'correct_answer': 'a full model answer', 'topic': 'T',
             'is_simulation': False, 'user_choice': None, 'skipped': False,
             'score': None, 'remark': None},
            {'index': 2, 'number': 3, 'section': 'B', 'type': 'Theory',
             'question_text': 'theory three', 'options': [],
             'correct_answer': 'another model answer', 'topic': 'T',
             'is_simulation': False, 'user_choice': None, 'skipped': False,
             'score': None, 'remark': None},
            # Hybrid the deterministic matcher settles on its own (no API call).
            {'index': 3, 'number': 4, 'section': 'B', 'type': 'Hybrid',
             'question_text': 'hybrid four', 'options': [],
             'correct_answer': 'paraphrased model answer', 'topic': 'T',
             'is_simulation': False, 'user_choice': None, 'skipped': False,
             'score': None, 'remark': None},
            # Hybrid that has to be batched for the evaluator to settle.
            {'index': 4, 'number': 5, 'section': 'B', 'type': 'Hybrid',
             'question_text': 'hybrid five', 'options': [],
             'correct_answer': 'a longer model answer about forces',
             'topic': 'T', 'is_simulation': False, 'user_choice': None,
             'skipped': False, 'score': None, 'remark': None},
        ],
    }
    quiz_note.save_note(note)
    quiz_note.write_theory_batches(note)
    return note


ANSWERS = [
    {'number': 1, 'user_choice': 'A. a', 'choice_meta': {'kind': 'option', 'index': 0}},
    {'number': 2, 'user_choice': 'my essay', 'choice_meta': {'kind': 'text'}},
    {'number': 3, 'user_choice': 'my other essay', 'choice_meta': {'kind': 'text'}},
    {'number': 4, 'user_choice': 'paraphrased model answer',
     'choice_meta': {'kind': 'text'}},
    # Deliberately not an exact match, so this one rides in a batch.
    {'number': 5, 'user_choice': 'forces act on it somehow',
     'choice_meta': {'kind': 'text'}},
]

try:
    # 1. "Mark later": History is written at once, theory left pending
    svc = FakeService()
    make_note('marklate1')
    res = quiz_grader.complete_quiz(svc, 'marklate1', ANSWERS, True,
                                    skip_mode='zero', topics=['T'],
                                    mark_subjective=False)
    check('mark-later reports pending', res['marking_pending'] is True)
    check('mark-later still writes History', res['history_written'] is True)
    hist = res['history_quiz_id']
    check('mark-later returns a history id', bool(hist))

    log = quiz_logger.load_quiz_log(hist)
    check('log exists', log is not None)
    check('log is flagged pending', log.marking_pending is True)
    check('log is complete', log.completed is True)

    mcq = next(q for q in log.questions if q.number == 1)
    check('MCQ is still marked locally', mcq.is_correct is True)

    subj = [q for q in log.questions if q.q_type in ('Theory', 'Hybrid')]
    check('subjective scores are all null', all(q.score is None for q in subj))
    check('subjective feedback is empty', all(not q.ai_feedback for q in subj))
    check('subjective answers are saved', all(q.user_answer for q in subj))
    check('no AI call was made yet', len(svc.batches) == 0)
    check('hybrid went into the batch stream, not its own calls',
          len(svc.hybrid_calls) == 0)

    # Hybrid is subjective, so it defers like Theory even though the strict
    # matcher could usually settle it for free.
    hyb = next(q for q in log.questions if q.number == 4)
    check('hybrid question exists in History', hyb.q_type == 'Hybrid')
    check('hybrid is pending after Mark later', hyb.score is None)
    check('hybrid has no feedback text', not hyb.ai_feedback)
    note_late = quiz_note.load_note('marklate1')
    hyb_note = next(e for e in note_late['questions'] if e['number'] == 4)
    check('hybrid is marked pending in the note', hyb_note['remark'] == 'pending')
    check('hybrid note score is null', hyb_note['score'] is None)
    hyb5 = next(q for q in log.questions if q.number == 5)
    check('fallback hybrid is pending too', hyb5.score is None)
    check('fallback hybrid has no feedback text', not hyb5.ai_feedback)

    # 2. "Mark now" (the default) grades everything up front.
    # History ids are second-precision, so pause to keep the two logs distinct.
    time.sleep(1.05)
    svc2 = FakeService()
    make_note('marknow1')
    res2 = quiz_grader.complete_quiz(svc2, 'marknow1', ANSWERS, True,
                                     skip_mode='zero', topics=['T'])
    check('mark-now is not pending', res2['marking_pending'] is False)
    check('mark-now called the AI', len(svc2.batches) >= 1)
    log2 = quiz_logger.load_quiz_log(res2['history_quiz_id'])
    check('mark-now log is not pending', log2.marking_pending is False)
    check('mark-now filled subjective scores',
          all(q.score is not None for q in log2.questions if q.q_type == 'Theory'))
    check('mark-now filled hybrid scores',
          all(q.score is not None for q in log2.questions if q.q_type == 'Hybrid'))

    # 3. Marking later patches the same entry in place
    svc3 = FakeService()
    out = quiz_grader.mark_pending_quiz(svc3, hist)
    check('mark-pending reports work done', out['marked'] == 4, f"marked={out['marked']}")
    check('mark-pending is no longer pending', out['marking_pending'] is False)
    check('mark-pending called the AI', len(svc3.batches) >= 1)
    # Hybrid is batched alongside Theory now, so it must not cost a call of
    # its own: the unmatched one rides in a batch instead.
    check('mark-pending used no per-question hybrid calls',
          svc3.hybrid_calls == [], f"hybrid_calls={svc3.hybrid_calls}")
    batched = [e for b in svc3.batches for e in b]
    check('the unmatched hybrid rode in a batch',
          any(e['label'] == '5' and e['type'] == 'Hybrid' for e in batched),
          f"labels={[e['label'] for e in batched]}")

    log3 = quiz_logger.load_quiz_log(hist)
    check('pending flag cleared on disk', log3.marking_pending is False)
    subj3 = [q for q in log3.questions if q.q_type == 'Theory']
    check('subjective scores now filled', all(q.score is not None for q in subj3))
    check('subjective feedback now filled', all(q.ai_feedback for q in subj3))
    hyb3 = next(q for q in log3.questions if q.number == 4)
    check('hybrid score filled by the later pass', hyb3.score == 1.0,
          f"score={hyb3.score}")
    # Under "Mark later" nothing is graded up front, so this exact match is
    # batched like any other subjective question and comes back right.
    check('exact-match hybrid is still marked right', hyb3.is_correct is True,
          f"correct={hyb3.is_correct} fb={hyb3.ai_feedback!r}")
    hyb5b = next(q for q in log3.questions if q.number == 5)
    check('batched hybrid score filled', hyb5b.score is not None,
          f"score={hyb5b.score}")
    # The fake evaluator reports full marks, so this one is right — which
    # proves the batch path ran and took over from the local matcher.
    check('batched hybrid was judged by the evaluator',
          hyb5b.score == 1.0 and hyb5b.is_correct is True,
          f"score={hyb5b.score} correct={hyb5b.is_correct}")
    note3 = quiz_note.load_note('marklate1')
    hyb3_note = next(e for e in note3['questions'] if e['number'] == 4)
    check('hybrid note mark replaced pending', hyb3_note['remark'] != 'pending',
          f"remark={hyb3_note['remark']}")
    check('MCQ verdict survived the patch',
          next(q for q in log3.questions if q.number == 1).is_correct is True)
    check('user answers survived the patch',
          all(q.user_answer for q in log3.questions))
    check('the same history id was patched', log3.quiz_id == hist)
    check('no extra history entry appeared', len(quiz_logger.list_quiz_logs()) == 2,
          f"count={len(quiz_logger.list_quiz_logs())}")

    # 4. Marking twice is safe and does not compound
    svc4 = FakeService()
    out4 = quiz_grader.mark_pending_quiz(svc4, hist)
    # Everything scored on the first pass, so the pending guard — which
    # snapshots state before grading — leaves the whole subjective tail alone.
    check('second pass re-grades nothing that is already marked',
          out4['marked'] == 0, f"marked={out4['marked']}")
    log4 = quiz_logger.load_quiz_log(hist)
    check('scores are still 1.0 not doubled',
          all(q.score == 1.0 for q in log4.questions if q.q_type == 'Theory'))
    check('hybrid is not re-graded once already marked',
          next(q for q in log4.questions if q.number == 4).score == 1.0)
    check('fallback hybrid keeps its evaluator verdict on a second pass',
          next(q for q in log4.questions if q.number == 5).score == 1.0)
    # Theory is fluid credit, so the patch must not invent a boolean verdict
    # just because it scored full marks.
    check('theory is_correct stays None after patching',
          all(q.is_correct is None for q in log4.questions if q.q_type == 'Theory'))
    check('the skip/unanswered guard held for hybrid',
          all('unanswered' not in (q.ai_feedback or '')
              for q in log4.questions if q.q_type == 'Hybrid'))
    check('no duplicate history entry', len(quiz_logger.list_quiz_logs()) == 2,
          f"count={len(quiz_logger.list_quiz_logs())}")

    # 5. Hybrid is strict: a near-miss earns nothing, while the same raw score
    # still earns Theory its partial credit.
    check('hybrid snaps to full marks at/above the pass threshold',
          quiz_note.snap_hybrid_score(1.0) == 1.0
          and quiz_note.snap_hybrid_score(0.5) == 1.0,
          f"1.0->{quiz_note.snap_hybrid_score(1.0)} "
          f"0.5->{quiz_note.snap_hybrid_score(0.5)}")
    check('hybrid snaps a near-miss down to zero',
          quiz_note.snap_hybrid_score(0.49) == 0.0
          and quiz_note.snap_hybrid_score(0.25) == 0.0,
          f"0.49->{quiz_note.snap_hybrid_score(0.49)} "
          f"0.25->{quiz_note.snap_hybrid_score(0.25)}")
    check('hybrid never returns a partial credit level',
          quiz_note.snap_hybrid_score(0.9) in (0.0, 1.0)
          and quiz_note.snap_hybrid_score(0.1) in (0.0, 1.0))
    check('hybrid snapping survives junk input',
          quiz_note.snap_hybrid_score(None) == 0.0
          and quiz_note.snap_hybrid_score('nonsense') == 0.0)
    check('theory keeps its five-level scale for the same inputs',
          quiz_note.snap_score(0.9) == 1.0 and quiz_note.snap_score(0.3) == 0.25,
          f"0.9->{quiz_note.snap_score(0.9)} 0.3->{quiz_note.snap_score(0.3)}")

    time.sleep(1.05)
    svc5 = FakeService(partial=0.4)  # a near-miss for every question
    make_note('binary1')
    res5 = quiz_grader.complete_quiz(svc5, 'binary1', ANSWERS, True,
                                     skip_mode='zero', topics=['T'])
    log5 = quiz_logger.load_quiz_log(res5['history_quiz_id'])
    hybs5 = [q for q in log5.questions if q.q_type == 'Hybrid']
    check('hybrid scored 0.0 despite a 0.4 raw score',
          all(q.score == 0.0 for q in hybs5),
          f"scores={[q.score for q in hybs5]}")
    check('hybrid is_correct is False on a near-miss',
          all(q.is_correct is False for q in hybs5),
          f"correct={[q.is_correct for q in hybs5]}")
    theo5 = [q for q in log5.questions if q.q_type == 'Theory']
    check('theory still earned partial credit from the same 0.4',
          all(q.score == 0.5 for q in theo5),
          f"scores={[q.score for q in theo5]}")
    check('theory has no boolean verdict',
          all(q.is_correct is None for q in theo5),
          f"correct={[q.is_correct for q in theo5]}")

    # 6. Hybrid leniency: a right answer phrased differently must still be
    #    right. The local matcher may only ever shortcut to RIGHT, and the
    #    batched prompt must not invite strict judging of wording.
    check('fast path accepts a case/whitespace difference',
          hybrid_marker.hybrid_exact_match('9.8 m/s^2', '9.8 m/s^2'))
    check('fast path accepts a trailing period and spacing difference',
          hybrid_marker.hybrid_exact_match(' 9.8 ', '9.8.'))
    check('fast path accepts a different but equivalent glyph',
          hybrid_marker.hybrid_exact_match('3 \u00d7 10', '3 x 10'),
          'x-glyph did not normalise')
    check('fast path accepts a unicode minus',
          hybrid_marker.hybrid_exact_match('\u22125', '-5'))
    check('fast path declines a different value rather than calling it wrong',
          hybrid_marker.hybrid_exact_match('9.9 m/s^2', '9.8 m/s^2') is False)
    check('fast path declines equivalent phrasing so the evaluator can judge it',
          hybrid_marker.hybrid_exact_match('about 2 x 10^30 kg',
                                           '1.99 x 10^30 kg') is False)

    prompt = prompts.build_theory_eval_prompt([{
        'label': '3', 'type': 'Hybrid', 'question': 'Mass of the Sun in kg?',
        'user_answer': 'about 2 x 10^30', 'correct_answer': '1.99e30 kg',
    }])
    check('hybrid is tagged binary, not strict',
          'BINARY' in prompt and 'STRICT' not in prompt)
    check('the tag says to judge meaning, not wording',
          'judge meaning, not wording' in prompt)
    check('the prompt states equivalent forms score full credit',
          'mathematically equivalent form' in prompt
          and 'different words' in prompt)
    check('the prompt forbids failing on phrasing alone',
          'merely because the phrasing differs' in prompt)
    check('the prompt still fails a real error',
          'wrong or missing unit' in prompt and '0.0' in prompt)

    theory_prompt = prompts.build_theory_eval_prompt([{
        'label': '2', 'type': 'Theory', 'question': 'Explain gravity',
        'user_answer': 'essay', 'correct_answer': 'model answer',
    }])
    check('theory entries carry no binary tag',
          '(BINARY' not in theory_prompt,
          'theory entry got the hybrid tag')
    # A Theory-only batch must not carry the binary rubric at all, or the model
    # may start scoring Theory as all-or-nothing and lose partial credit.
    check('a theory-only batch omits the binary rubric entirely',
          'marked BINARY' not in theory_prompt
          and 'score exactly 1.0 or exactly 0.0' not in theory_prompt,
          'binary rubric leaked into a theory-only prompt')
    check('a theory-only batch still gets the format instructions',
          'QUESTION <number> / SCORE / EVALUATION' in theory_prompt)

    # A batch mixing both types keeps the rubric AND says non-BINARY entries
    # still earn partial credit, so the rubric cannot leak onto Theory.
    mixed_prompt = prompts.build_theory_eval_prompt([
        {'label': '2', 'type': 'Theory', 'question': 'Explain gravity',
         'user_answer': 'essay', 'correct_answer': 'model answer'},
        {'label': '3', 'type': 'Hybrid', 'question': 'Mass of the Sun?',
         'user_answer': 'about 2 x 10^30', 'correct_answer': '1.99e30 kg'},
    ])
    check('a mixed batch keeps the binary rubric',
          'marked BINARY' in mixed_prompt)
    check('a mixed batch tells the model non-BINARY keeps partial credit',
          'may earn partial' in mixed_prompt)
    check('only the hybrid entry is tagged in a mixed batch',
          mixed_prompt.count('(BINARY') == 1
          and 'QUESTION 3 (BINARY' in mixed_prompt,
          f"tags={mixed_prompt.count('(BINARY')}")

    # An entry with no 'type' key is legacy data and must not trigger the rule.
    legacy_prompt = prompts.build_theory_eval_prompt([
        {'label': '5', 'question': 'q', 'user_answer': 'a',
         'correct_answer': 'b'},
    ])
    check('a legacy entry with no type does not trigger the binary rubric',
          'marked BINARY' not in legacy_prompt)

    # 7. Errors are surfaced, not swallowed
    for bad in ('doesnotexist', ''):
        try:
            quiz_grader.mark_pending_quiz(FakeService(), bad)
            check(f'rejects unknown quiz {bad!r}', False, 'no error')
        except ValueError:
            check(f'rejects unknown quiz {bad!r}', True)

    # 6. Old logs without the field still load (back-compat)
    raw = quiz_logger.LOGS_DIR / f'quiz_{hist}.json'
    import json
    data = json.loads(raw.read_text())
    data.pop('marking_pending', None)
    raw.write_text(json.dumps(data))
    legacy = quiz_logger.load_quiz_log(hist)
    check('legacy log without the field loads', legacy is not None)
    check('legacy log defaults to not pending', legacy.marking_pending is False)
    check('list_quiz_logs tolerates a missing field',
          all(isinstance(s['marking_pending'], bool)
              for s in quiz_logger.list_quiz_logs()))

    print(f'\n{PASS} passed, {FAIL} failed')
    sys.exit(1 if FAIL else 0)
finally:
    shutil.rmtree(_TMP, ignore_errors=True)
