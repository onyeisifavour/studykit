"""Every "Generate Quiz" starts a fresh set of pipeline sessions.

Regression cover for stale generation context leaking between quizzes: the
per-run pipeline agents must be reset per generation, while the five pre-quiz
chat agents keep their sessions (they belong to the chat).

Run: python tests/test_generation_sessions.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from unittest import mock

from main_app import config
from main_app.agent_runner import AgentRunner, GENERATION_AGENTS, PREQUIZ_AGENTS
from main_app.api_client import CLIBridgeClient

PASS, FAIL = 0, 0


def check(label, cond, extra=''):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f'PASS {label}')
    else:
        FAIL += 1
        print(f'FAIL {label} {extra}')


def test_start_generation_resets_generation_but_not_prequiz():
    stored = {
        PREQUIZ_AGENTS[0]: 'ses_chat',
        PREQUIZ_AGENTS[1]: 'ses_knowledge',
        GENERATION_AGENTS[0]: 'ses_quota',
        GENERATION_AGENTS[3]: 'ses_sim',
    }

    def fake_set_value(key, value):
        if key == 'agent_sessions':
            stored.clear()
            stored.update(value)

    with mock.patch.object(config, 'get_agent_sessions',
                           side_effect=lambda: dict(stored)), \
            mock.patch.object(config, 'get_pending_messages', return_value={}), \
            mock.patch.object(config, 'set_value', side_effect=fake_set_value):
        runner = AgentRunner(CLIBridgeClient())
        runner._sessions.update(stored)
        runner.start_generation()

    check('generation sessions dropped from memory',
          all(a not in runner._sessions for a in GENERATION_AGENTS),
          runner._sessions)
    check('generation sessions dropped from config',
          all(a not in stored for a in GENERATION_AGENTS), stored)
    check('pre-quiz chat sessions preserved',
          stored.get(PREQUIZ_AGENTS[0]) == 'ses_chat'
          and stored.get(PREQUIZ_AGENTS[1]) == 'ses_knowledge', stored)
    check('run workspace reset for the new generation',
          runner._run_dir is None, runner._run_dir)


def run():
    test_start_generation_resets_generation_but_not_prequiz()
    print(f'\n{PASS} passed, {FAIL} failed')
    sys.exit(1 if FAIL else 0)


if __name__ == '__main__':
    run()
