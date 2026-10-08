"""Inline test for history log deletion (quiz_logger + the sidecar route)."""
import sys
import os
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main_app import quiz_logger
from main_app.quiz_logger import QuizLog

print('PASS 0: module import')

GOOD_ID = '20260924_131830'

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    logs = root / 'logs'
    logs.mkdir()
    quiz_logger.LOGS_DIR = logs

    # 1. Removing an existing log reports True
    quiz_logger.save_quiz_log(QuizLog(quiz_id=GOOD_ID,
                                      created_at='2026-01-01T00:00:00',
                                      topics=['Physics: Kinematics']))
    other = '20260911_050443'
    quiz_logger.save_quiz_log(QuizLog(quiz_id=other,
                                      created_at='2026-01-01T00:00:00',
                                      topics=['x']))
    assert (logs / f'quiz_{GOOD_ID}.json').exists()
    assert quiz_logger.delete_quiz_log(GOOD_ID) is True
    assert not (logs / f'quiz_{GOOD_ID}.json').exists()
    print('PASS 1: existing log deleted')

    # 2. Deleting again is a no-op, not an error
    assert quiz_logger.delete_quiz_log(GOOD_ID) is False
    print('PASS 2: deleting a missing log returns False')

    # 3. Siblings are untouched
    assert (logs / f'quiz_{other}.json').exists()
    assert len(quiz_logger.list_quiz_logs()) == 1
    print('PASS 3: other history entries are untouched')

    # 4. Malformed ids are rejected before reaching the filesystem
    for bad in ('../secrets', '..', 'a/b', '20260924', '', 'x' * 300,
                '20260924_131830/../../etc/passwd', None):
        assert not quiz_logger.is_valid_quiz_id(bad), bad
        try:
            quiz_logger.delete_quiz_log(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f'accepted malformed id: {bad!r}')
    print('PASS 4: malformed ids rejected, including traversal attempts')

    # 5. Valid ids are accepted by the validator
    assert quiz_logger.is_valid_quiz_id(GOOD_ID)
    assert quiz_logger.is_valid_quiz_id('20260101_000000')
    print('PASS 5: well-formed ids accepted')

    # 6. list_quiz_logs no longer reports the deleted entry
    ids = [s['quiz_id'] for s in quiz_logger.list_quiz_logs()]
    assert GOOD_ID not in ids and other in ids, ids
    print('PASS 6: deleted entry disappears from the listing')

print('\nAll history-delete tests passed.')
