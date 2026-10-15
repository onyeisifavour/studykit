"""Chat-session lifecycle: starting a new chat resets the five pre-quiz agents
and leaves the quiz store (instances/artifacts) untouched.

The pre-quiz agents (main chat + the four background models) are NOT a durable
learner profile — they belong to the current chat and share one lifetime.

Run: python tests/test_profile_retention.py
"""

import os
import shutil
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_TMP = Path(tempfile.mkdtemp(prefix='quiz-profile-test-'))
os.environ['HOME'] = str(_TMP)
os.environ['XDG_CONFIG_HOME'] = str(_TMP / '.config')

for _m in [m for m in list(sys.modules) if m.startswith('main_app')]:
    del sys.modules[_m]

from main_app import config
from main_app.agent_runner import AgentRunner, ALL_BG_AGENTS, PREQUIZ_AGENTS

PASS, FAIL = 0, 0


def check(label, cond, extra=''):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f'PASS {label}')
    else:
        FAIL += 1
        print(f'FAIL {label} {extra}')


def _bare_runner():
    r = AgentRunner.__new__(AgentRunner)   # skip the CLI client / network
    r._sessions = {
        'pre-quiz_main_chat':       'ses_chat',
        'knowledge-graph-builder':  'ses_k',
        'misconception-classifier': 'ses_m',
        'mechanism-evaluator':      'ses_me',
        'drill-recommender':        'ses_d',
        'diagnostic-quota-planner': 'ses_q',
        'agent2a-topic-resolver':   'ses_2a',
    }
    r._pending = {'knowledge-graph-builder': [{'message': 'queued'}]}
    r._bg_reports = {'knowledge-graph-builder': 'report'}
    r._lock = threading.RLock()
    r._bg_busy = {a: False for a in ALL_BG_AGENTS}
    r._bg_digest_sent = {a: True for a in ALL_BG_AGENTS}
    return r


def _seed_config():
    config.save({})
    config.set_value('agent_sessions', {
        'pre-quiz_main_chat':       'ses_chat',
        'knowledge-graph-builder':  'ses_k',
        'diagnostic-quota-planner': 'ses_q',
    })
    config.set_value('pending_messages', {'knowledge-graph-builder': [{'message': 'queued'}]})


def test_has_prequiz_session():
    runner = _bare_runner()
    _seed_config()
    check('has_prequiz_session true when chat agents exist',
          runner.has_prequiz_session() is True)
    config.save({})
    check('has_prequiz_session false when none exist',
          runner.has_prequiz_session() is False)


def test_new_chat_resets_all_five_and_keeps_quiz_store():
    runner = _bare_runner()
    _seed_config()

    # A quiz instance on disk, which a new chat must never disturb.
    inst = _TMP / '.quiz_app' / 'instances'
    inst.mkdir(parents=True, exist_ok=True)
    marker = inst / 'keep-me.json'
    marker.write_text('{"quiz_id": "keep-me"}', encoding='utf-8')

    runner.clear_sessions()

    for agent in PREQUIZ_AGENTS:
        check(f'{agent} cleared from memory', agent not in runner._sessions)
        check(f'{agent} cleared from config', agent not in config.get_agent_sessions())
    check('per-run agents cleared too', 'diagnostic-quota-planner' not in runner._sessions)
    check('queued messages cleared',
          'knowledge-graph-builder' not in runner._pending
          and config.get_pending_messages() == {})
    check('in-memory reports cleared', runner._bg_reports == {})
    check('has_prequiz_session now false', runner.has_prequiz_session() is False)
    check('quiz instance store untouched', marker.exists())


def run():
    test_has_prequiz_session()
    test_new_chat_resets_all_five_and_keeps_quiz_store()
    print(f'\n{PASS} passed, {FAIL} failed')
    shutil.rmtree(_TMP, ignore_errors=True)
    return FAIL


if __name__ == '__main__':
    sys.exit(1 if run() else 0)
