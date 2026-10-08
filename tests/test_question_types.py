"""Inline test for question-type normalisation in quiz_logger + dashboard_stats.

The bug this guards: quiz notes write the pipeline's 'MCQ'|'Hybrid'|'Theory'
into QuestionRecord.q_type, but the stats helpers compared against the
log-level 'SUBJ'|'SIM'. Every Hybrid/Theory question therefore fell through to
"contributes nothing" and scored 0 in History avg_pct and the Dashboard.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main_app import quiz_logger, dashboard_stats
from main_app.quiz_logger import QuizLog, QuestionRecord

print('PASS 0: module import')


def mk(q_type, **kw):
    base: dict = dict(index=0, number=1, question='q', section='B',
                      q_type=q_type, is_simulation=False, correct_answer='A')
    base.update(kw)
    return QuestionRecord(**base)


# 1. Type predicates
assert quiz_logger.is_local_type('MCQ') and quiz_logger.is_local_type('mcq')
assert not quiz_logger.is_local_type('Theory')
for t in ('SUBJ', 'Theory', 'Hybrid', 'SIM', 'theory', ' hybrid '):
    assert quiz_logger.is_ai_type(t), t
assert not quiz_logger.is_ai_type('MCQ')
assert not quiz_logger.is_ai_type('') and not quiz_logger.is_ai_type(None)
print('PASS 1: type predicates normalise case/whitespace and split local vs AI')


# 2. The actual bug — Theory/Hybrid previously scored 0
log = QuizLog(quiz_id='T', created_at='2026-01-01T00:00:00', topics=[],
              skip_mode='zero')
log.questions = [
    mk('MCQ', index=0, number=1, is_correct=True),
    mk('Theory', index=1, number=2, score=0.5),
    mk('Hybrid', index=2, number=3, score=1.0),
    mk('SUBJ', index=3, number=4, score=0.25),
]
assert log.mcq_score() == (1, 1)
assert log.subj_score() == (1.75, 3), log.subj_score()
print('PASS 2: subj_score() counts Theory + Hybrid + legacy SUBJ')


# 3. Unscored AI questions contribute nothing (pre-marking / mark-later)
log2 = QuizLog(quiz_id='U', created_at='2026-01-01T00:00:00', topics=[])
log2.questions = [mk('Theory', score=None, is_correct=None)]
assert log2.subj_score() == (0.0, 0), log2.subj_score()
assert dashboard_stats._question_credit(log2, log2.questions[0]) is None
print('PASS 3: unscored AI questions are excluded, not counted as zero')


# 4. _question_credit now reaches Theory
assert dashboard_stats._question_credit(log, log.questions[1]) == (0.5, 1)
assert dashboard_stats._question_credit(log, log.questions[2]) == (1.0, 1)
print('PASS 4: _question_credit() scores Theory/Hybrid records')


# 5. skip_mode still honoured across both vocabularies
log3 = QuizLog(quiz_id='S', created_at='2026-01-01T00:00:00', topics=[],
               skip_mode='exclude')
log3.questions = [
    mk('MCQ', index=0, number=1, is_correct=True),
    mk('Theory', index=1, number=2, score=1.0, skipped=True),
    mk('Hybrid', index=2, number=3, score=0.5),
]
assert log3.mcq_score() == (1, 1)
assert log3.subj_score() == (0.5, 1), log3.subj_score()
print('PASS 5: skip_mode=exclude filters Theory/Hybrid too')


# 6. from_dict is forward/backward compatible and no longer mutates its input
raw = {
    'quiz_id': 'F', 'created_at': '2026-01-01T00:00:00', 'topics': ['t'],
    'questions': [{'index': 0, 'number': 1, 'question': 'q', 'section': 'A',
                   'q_type': 'Theory', 'is_simulation': False,
                   'correct_answer': 'A', 'score': 0.75}],
    'a_field_from_a_future_version': 'ignored',
}
snapshot = dict(raw)
parsed = QuizLog.from_dict(raw)
assert raw == snapshot, 'from_dict mutated the caller dict'
assert 'a_field_from_a_future_version' not in parsed.__dict__
assert parsed.questions[0].score == 0.75
assert parsed.subj_score() == (0.75, 1)
print('PASS 6: from_dict tolerates unknown keys and leaves input untouched')


# 7. End-to-end: a real note written through quiz_grader must reach the Dashboard.
# quiz_note._canonical_type can only emit 'MCQ'|'Hybrid'|'Theory', so the old
# `q_type == 'SUBJ'` filter in subj_score() was unreachable — every Theory and
# Hybrid question was silently dropped from History and the Dashboard.
import tempfile
from pathlib import Path

from main_app import quiz_note, quiz_grader

with tempfile.TemporaryDirectory() as tmp:
    tmp_logs = Path(tmp) / 'logs'
    real_logs, real_marked = quiz_logger.LOGS_DIR, quiz_note.set_history_written
    quiz_logger.LOGS_DIR = tmp_logs
    quiz_note.set_history_written = lambda *a, **k: None
    try:
        note = {
            'quiz_id': 'E2E', 'topics': ['Physics: Kinematics'],
            'questions': [
                {'index': 0, 'number': 1, 'type': 'MCQ', 'section': 'A',
                 'question_text': 'mcq', 'options': ['A', 'B'], 'skipped': False,
                 'user_choice': 'A', 'score': 1.0},
                {'index': 1, 'number': 2, 'type': 'Theory', 'section': 'B',
                 'question_text': 'theory', 'options': [], 'skipped': False,
                 'user_choice': 'an answer', 'score': 0.8,
                 'remark': 'partial'},
                {'index': 2, 'number': 3, 'type': 'Hybrid', 'section': 'B',
                 'question_text': 'hybrid', 'options': ['A', 'B'],
                 'skipped': False, 'user_choice': 'B', 'score': 0.4,
                 'remark': 'weak'},
            ],
        }
        log_id = quiz_grader._write_quiz_log(note, True, 'zero', note['topics'])
        written = quiz_logger.load_quiz_log(log_id)
        assert written is not None, 'log did not round-trip'
        assert [q.q_type for q in written.questions] == ['MCQ', 'Theory', 'Hybrid']
        subj_total, subj_n = written.subj_score()
        assert abs(subj_total - 1.2) < 1e-9 and subj_n == 2, (subj_total, subj_n)

        dash = dashboard_stats.build_dashboard(logs_dir=tmp_logs)
        # credit 1.0 + 0.8 + 0.4 = 2.2 over weight 3 → 73%
        assert dash['avg_pct'] == 73, dash['avg_pct']
        assert dash['questions'] == 3
        assert dash['subjects'] and dash['subjects'][0]['name'] == 'Physics'
    finally:
        quiz_logger.LOGS_DIR = real_logs
        quiz_note.set_history_written = real_marked
print('PASS 7: end-to-end Theory/Hybrid now reach History and Dashboard stats')

print('\nAll question-type tests passed.')
