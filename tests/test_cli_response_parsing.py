"""
test_cli_response_parsing.py

Regression tests for parsing opencode's `--format json` stream.

The leak this guards against: an agentic run emits one text part per step
(intermediate narration between tool calls, then the final answer) and some
models fold their private reasoning into the same part, terminated by a
closing tag such as `</think>`. Concatenating every text part surfaced the
narration and the chain-of-thought to the student. Only the final text part,
with its thinking stripped, should ever be returned.

Run: python tests/test_cli_response_parsing.py
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from main_app.api_client import (  # noqa: E402
    _extract_response_from_json,
    _strip_model_thinking,
)

CLOSE = '</think>'


def _text_event(part_id: str, text: str, session: str = 'ses_top') -> str:
    return json.dumps({
        'type': 'text',
        'sessionID': session,
        'part': {
            'id': part_id,
            'sessionID': session,
            'type': 'text',
            'text': text,
        },
    })


# 1. Inline chain-of-thought before the closing tag is stripped.
cleaned = _strip_model_thinking(f'scratch. more scratch.{CLOSE}Final answer.')
assert cleaned == 'Final answer.', repr(cleaned)
print('PASS 1: inline thinking is stripped')


# 2. Text without any thinking tag is returned unchanged.
assert _strip_model_thinking('Which statement best shows the rule?') == \
    'Which statement best shows the rule?'
print('PASS 2: text without thinking is unchanged')


# 3. A multi-step stream returns only the final answer, not the narration.
stream = '\n'.join([
    _text_event('p1', "I'll locate the concept block files.\n"),
    _text_event('p2', 'Let me read the available concept blocks.\n'),
    _text_event('p3', f'Reasoning about the student.{CLOSE}Which statement best shows the rule? Justify briefly.'),
])
text, session = _extract_response_from_json(stream)
assert text == 'Which statement best shows the rule? Justify briefly.', repr(text)
assert session == 'ses_top', session
print('PASS 3: only the final answer is returned; narration and thinking are dropped')


# 4. Text from an interleaved child (subagent) session is never returned.
stream = '\n'.join([
    _text_event('p1', 'Final student-facing answer.'),
    _text_event('c1', 'Subagent digest output that must not surface.', session='ses_child'),
])
text, session = _extract_response_from_json(stream)
assert text == 'Final student-facing answer.', repr(text)
assert session == 'ses_top', session
print('PASS 4: child-session output is filtered out')


# 5. Inline reasoning in a single part is stripped end to end.
stream = _text_event('p1', f'Reasoning here.{CLOSE}hello world')
text, _ = _extract_response_from_json(stream)
assert text == 'hello world', repr(text)
print('PASS 5: inline reasoning in a single part is stripped')


# 6. An empty trailing text part does not hide the real answer.
stream = '\n'.join([
    _text_event('p1', 'The real answer.'),
    _text_event('p2', '   '),
])
text, _ = _extract_response_from_json(stream)
assert text == 'The real answer.', repr(text)
print('PASS 6: empty trailing parts are ignored')


print('\nAll CLI response parsing tests passed.')
