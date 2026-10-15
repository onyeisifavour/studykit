"""Generation guard: generation fails fast and clearly when there are no topics.

Also covers the candidate-pool check that turns "zero candidates for every
slot" (the signature of an unchecked/empty topic set) into a clear error
instead of an opaque "empty selected-items list" failure in the sequencer.

Run: python tests/test_generation_guard.py
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_TMP = Path(tempfile.mkdtemp(prefix='quiz-guard-test-'))
os.environ['HOME'] = str(_TMP)
os.environ['XDG_CONFIG_HOME'] = str(_TMP / '.config')

for _m in [m for m in list(sys.modules) if m.startswith('main_app')]:
    del sys.modules[_m]

from main_app import config
from main_app import library_scanner
from main_app.manifest_validator import validate_candidate_pool
from main_app.quiz_service import (
    QuizService,
    NO_TOPICS_ERROR,
    NO_LOADABLE_TOPICS_ERROR,
)

PASS, FAIL = 0, 0


def check(label, cond, extra=''):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f'PASS {label}')
    else:
        FAIL += 1
        print(f'FAIL {label} {extra}')


def _bare_service():
    svc = QuizService.__new__(QuizService)   # skip _build_clients / network
    svc._agent_runner = None
    svc._api = None
    svc._runner = None
    return svc


def test_empty_topics_fails_fast():
    svc = _bare_service()
    reached = []
    svc._legacy_generate = lambda *a, **k: reached.append('legacy')
    err = {}
    svc.generate_quiz(
        user_request='x',
        topic_files=[],
        on_error=lambda stage, msg: err.update(stage=stage, msg=msg),
    )
    check('empty topics fails with NO_TOPICS_ERROR', err.get('msg') == NO_TOPICS_ERROR, err)
    check('empty topics never reaches the pipeline', not reached, reached)


def test_nonempty_topics_passes_the_guard():
    svc = _bare_service()
    reached = []
    svc._legacy_generate = lambda *a, **k: reached.append('legacy')
    svc.generate_quiz(user_request='x', topic_files=[{'topic': 'L1.1'}],
                      on_error=lambda *a: reached.append('err'))
    check('non-empty topics proceeds past the guard', reached == ['legacy'], reached)


def test_all_empty_candidate_pool_is_an_error():
    errors = validate_candidate_pool({1: [], 2: [], 3: []})
    check('pool with zero candidates everywhere is flagged',
          any('empty for every slot' in e for e in errors), errors)


def test_populated_candidate_pool_is_valid():
    pool = {1: [{'question_text': 'What is 2+2?', 'tags': {}}]}
    check('a populated pool passes', validate_candidate_pool(pool) == [],
          validate_candidate_pool(pool))


def test_missing_topic_paths_are_tolerated():
    check('nonexistent topic paths yield [] without raising',
          library_scanner.load_selected_topics(['/definitely/not/here/L9.9']) == [])


def test_selected_but_unloadable_topics_get_their_own_message():
    config.save({'selected_topics': ['/definitely/not/here/L9.9']})
    svc = _bare_service()
    err = {}
    svc._legacy_generate = lambda *a, **k: None
    svc.generate_quiz(
        user_request='x',
        topic_files=[],
        on_error=lambda stage, msg: err.update(stage=stage, msg=msg),
    )
    check('selected-but-unloadable topics report NO_LOADABLE_TOPICS_ERROR',
          err.get('msg') == NO_LOADABLE_TOPICS_ERROR, err)
    config.save({})


def run():
    test_empty_topics_fails_fast()
    test_nonempty_topics_passes_the_guard()
    test_all_empty_candidate_pool_is_an_error()
    test_populated_candidate_pool_is_valid()
    test_missing_topic_paths_are_tolerated()
    test_selected_but_unloadable_topics_get_their_own_message()
    print(f'\n{PASS} passed, {FAIL} failed')
    shutil.rmtree(_TMP, ignore_errors=True)
    return FAIL


if __name__ == '__main__':
    sys.exit(1 if run() else 0)
