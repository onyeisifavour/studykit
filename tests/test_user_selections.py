"""Inline test for main_app.user_selections manifest logic + extractor."""
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main_app import config
from main_app.user_selections import (
    load_manifest, save_manifest, reset_manifest,
    merge_manifest, build_request_block, check_manifest_against_plan,
    extract_manifest_diff, _EMPTY_MANIFEST,
)

reset_manifest()

# 1. Defaults
m = load_manifest()
assert m['intent'] is None
assert m['sections']['a_sim'] is True
print('PASS 1: load default')

# 2. Save/reload
m['intent'] = 'quick_test'
m['_intent_confidence'] = 0.95
save_manifest(m)
assert load_manifest()['intent'] == 'quick_test'
save_manifest(dict(_EMPTY_MANIFEST))
print('PASS 2: save/reload')

# 3. Merge chat count
merged = merge_manifest(load_manifest(),
                        {'question_count': 5, 'question_count_source': 'chat'}, turn_index=3)
assert merged['question_count'] == 5 and merged['count_source'] == 'chat'
print('PASS 3: merge chat count')

# 4. Form count preserved over chat
m4 = dict(_EMPTY_MANIFEST); m4['question_count'] = 10; m4['count_source'] = 'form'
merged2 = merge_manifest(m4, {'question_count': 5, 'question_count_source': 'chat'}, turn_index=4)
assert merged2['question_count'] == 10
print('PASS 4: form count preserved')

# 5. Exclusions dedupe
m5 = dict(_EMPTY_MANIFEST)
m5['question_count'] = 5
m5['count_source'] = 'chat'
m5['exclusions'] = [{'topic': 'Fluid Dynamics', 'reason': '', 'from_turn': 1, 'confidence': 0.9}]
merged3 = merge_manifest(m5, {'exclusions': [
    {'topic': 'Fluid Dynamics', 'reason': 'dup', 'confidence': 0.95},
    {'topic': 'Thermo', 'reason': 'new', 'confidence': 0.8},
]}, turn_index=5)
topics = [e['topic'] for e in merged3['exclusions']]
assert topics.count('Fluid Dynamics') == 1 and 'Thermo' in topics
print('PASS 5: exclusions dedup')

# 6. Request block render
block = build_request_block(merged3, 'hi',
                            form_prefs={'section_a_sim': True, 'section_a_nonsim': False})
assert 'USER SELECTIONS (authoritative' in block
assert 'Simulation questions included' in block
assert 'Non-simulation questions included' not in block
print('PASS 6: request block renders')

# 7. Machine-check violations
plan = {
    'total_questions': 10,
    'ordered_quiz_sequence': [
        {'slot_number': 1, 'format': 'Non-Sim', 'topic': 'Fluid Dynamics'},
        {'slot_number': 2, 'format': 'Sim', 'topic': 'Quantum'},
    ],
}
violations = check_manifest_against_plan(merged3, plan)
assert len(violations) >= 2, f'got {violations}'
assert any('count' in v.lower() for v in violations)
assert any('Fluid Dynamics' in v for v in violations)
print(f'PASS 7: machine-check ({len(violations)} violations)')

# 8. Extractor success path
class GoodClient:
    def __init__(self): self.called = False; self.agent = None
    def call(self, agent=None, session_id=None, system='', user='', on_success=None, on_error=None):
        self.called = True; self.agent = agent
        assert agent is None
        on_success(json.dumps({
            'intent': 'quick_test',
            'question_count': 3,
            'question_count_source': 'chat',
            'exclusions': [{'topic': 'X', 'reason': 'y', 'from_turn': 1, 'confidence': 0.9}],
        }), 's1')

gc = GoodClient()
diff = extract_manifest_diff('student: make it short', _EMPTY_MANIFEST, gc, timeout=10.0)
assert gc.called and gc.agent is None
assert diff == {'intent': 'quick_test', 'question_count': 3, 'question_count_source': 'chat',
                'exclusions': [{'topic': 'X', 'reason': 'y', 'from_turn': 1, 'confidence': 0.9}]}, diff
print('PASS 8: extractor success path')

# 9. Markdown-fenced response
class FencedClient:
    def call(self, agent=None, session_id=None, system='', user='', on_success=None, on_error=None):
        on_success('```json\n' + json.dumps({'difficulty': 'basic'}) + '\n```', 's2')

diff2 = extract_manifest_diff('hi', _EMPTY_MANIFEST, FencedClient(), timeout=10.0)
assert diff2 == {'difficulty': 'basic'}, diff2
print('PASS 9: fenced response stripped')

# 10. Error + garbage paths
class ErrClient:
    def call(self, agent=None, session_id=None, system='', user='', on_success=None, on_error=None):
        on_error('boom')

class GarbageClient:
    def call(self, agent=None, session_id=None, system='', user='', on_success=None, on_error=None):
        on_success('not json', 's3')

assert extract_manifest_diff('hi', _EMPTY_MANIFEST, ErrClient(), timeout=10.0) is None
assert extract_manifest_diff('hi', _EMPTY_MANIFEST, GarbageClient(), timeout=10.0) is None
print('PASS 10: error and garbage paths return None')

# ── Math-notation checker ─────────────────────────────────────────────────────
from main_app.user_selections import check_math_notation, _strip_math_spans

# 11. Flags plain-ASCII math in Sim slots
bad_seq = {
    'ordered_quiz_sequence': [
        {'sequence_index': 1, 'question': {
            'format': 'Sim',
            'text': 'Compute the force given GMm/r^2 where m is 1.89 x 10^26 kg.',
            'options': ['A. 10^5 N', 'B. 2 m/s', 'C. 3.0*10^4', 'D. 0'],
            'correct_answer': 'A',
            'sim_instruction': 'Use kepler formula GMm/r^2.',
        }},
    ],
}
viol = check_math_notation(bad_seq)
assert len(viol) >= 4, viol
assert any('caret_exponent' in v for v in viol)
assert any('x_as_times' in v for v in viol)
assert any('asterisk_times' in v for v in viol)
assert any('options:' not in v for v in viol)
print('PASS 11: flags plain-ASCII math in Sim slots')

# 12. Ignores compliant LaTeX spans and Non-Sim (verbatim) slots
good_seq = {
    'ordered_quiz_sequence': [
        {'sequence_index': 2, 'question': {
            'format': 'Sim',
            'text': 'The force is $F = G\\frac{m_1 m_2}{r^2}$ and $1.89\\times10^{26}$.',
            'options': ['A. $5\\times10^5\\ \\mathrm{N}$'],
            'correct_answer': 'A',
            'sim_instruction': 'Set $v = r\\omega$.',
        }},
        {'sequence_index': 3, 'question': {
            'format': 'Non-Sim',
            'text': 'Raw bank text with 10^25 and x-as-times here is verbatim.',
        }},
    ],
}
assert check_math_notation(good_seq) == [], check_math_notation(good_seq)
print('PASS 12: compliant LaTeX + Non-Sim verbatim slots pass')

# 13. _strip_math_spans removes all delimited forms (inline, block, equation env)
s = _strip_math_spans('a $x^2$ b $$y^2$$ c \\begin{equation}z^2\\end{equation} d 10^2')
assert 'MATH' in s and '10^2' in s, s
assert '^' not in s.replace('10^2', ''), s
print('PASS 13: strip_math_spans handles $, $$, equation env')

# 14. normalize_ascii_math repairs the exact legacy complaint patterns
from main_app.user_selections import normalize_ascii_math as _norm
r = _norm('F_gravity = G M m / r^2, approximately 1.18 x 10^25 x (1.0/0.5)^2 N.')
assert '1.18\\times10^{25}\\times(1.0/0.5)^{2}' in r, r
assert '(1.0/0.5)^{2}' in r and '$' in r, r
r2 = _norm('The force is 1.89 x 10^26 N and g = 9.8 m/s^2.')
assert '1.89\\times10^{26}' in r2, r2
assert '9.8 m/s$^{2}$' in r2, r2
r3 = _norm('Multiply 3*10^4 by 2.')
assert '3\\times10^{4}' in r3, r3
print('PASS 14: normalizer repairs ASCII math to LaTeX')

# 15. Normalizer leaves prose and compliant spans untouched
p = _norm('There are 3 apples in 2 baskets, all measured again.')
assert p == 'There are 3 apples in 2 baskets, all measured again.', p
q = _norm('This is $F = Gm/r^2$ and also 10^2 plain text.')
assert '$F = Gm/r^2$' in q and '10^{2}' in q, q
assert p.count('$') == 0
print('PASS 15: normalizer never touches prose or compliant spans')

reset_manifest()
print('\nAll 15 tests passed.')