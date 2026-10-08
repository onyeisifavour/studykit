"""Inline tests for main_app.option_generator: the stage-1b MCQ option writer.

Covers the three things that matter:
  1. options STATE the answer and do not explain it (the length-cue defect)
  2. the mechanical item-writing rules hold
  3. grading survives a reworded correct option via correct_option_index
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main_app.option_generator import (
    audit_options, build_option_prompt, normalise_option, parse_option_response,
    unit_of, NUM_OPTIONS, LENGTH_SPREAD_LIMIT,
)
from main_app.question_generator import (
    GeneratedQuestion, shuffle_mcq_options, _coerce_index,
)
from main_app.quiz_grader import _correct_option_index

# ── Fixtures ──────────────────────────────────────────────────────────────────

ITEM = {
    'slot_number': 3,
    'objective_type': 'apply',
    'target_issue': 'treats gravity as linear in separation',
    'selected_question': {
        'text': 'Halve the separation and quadruple both masses. '
                'What force does the simulation read?',
        'type': 'MCQ',
        'correct_answer': '7.55 x 10^26 N',
        'sim_instruction': 'Set distance 0.5 AU, masses 4.0 and 0.004.',
    },
}


def _response(options, correct_index=0, rationales=None, error_types=None):
    if rationales is None:
        rationales = [''] + ['You likely <mistake>.' for _ in options[1:]]
    if error_types is None:
        error_types = ['correct'] + [f'error-{i}' for i in range(len(options) - 1)]
    return json.dumps({
        'slot_number': 3,
        'options': options,
        'correct_index': correct_index,
        'rationales': rationales,
        'error_types': error_types,
    })


# 1. unit_of reads the trailing unit the way real output writes it
assert unit_of('8.2 m') == 'm'
assert unit_of('12 km/s') == 'km/s'
assert unit_of('10 m/s^2') == 'm/s'
assert unit_of('1.89 x 10^26 N') == 'n'
assert unit_of('0.004 M_sun') == 'sun'
assert unit_of('$1.89\\times10^{26}\\ \\mathrm{N}$') == 'n'
assert unit_of('1.18 x 10^25') == ''      # no unit
assert unit_of('2x') == ''                # glued multiplier, not a unit
print('PASS 1: unit_of reads trailing units, including real ASCII notation')

# 2. enumerator labels are stripped from both display and comparison
assert normalise_option('C. 4.5 m') == '4.5 m'
assert normalise_option('(b) 3 m') == '3 m'
print('PASS 2: leading A./B) labels are stripped')

# 3. The defect this stage exists to fix: a correct option that is the longest.
long_correct = ('1.89 x 10^26 N. The force scales linearly with each mass and '
                'inversely with the square of the separation, so the stacking '
                'gives a factor of 4 x 4 x 4 = 64 overall.')
w = audit_options([long_correct, '3.78 x 10^26 N', '1.89 x 10^26 N', '9.4 x 10^26 N'], 0)
assert any('CORRECT option' in x for x in w), w
print('PASS 3: a longest-correct-option item is flagged as giving the answer away')

# 4. Balanced options pass the length check
balanced = ['7.55 x 10^26 N', '3.78 x 10^26 N', '1.89 x 10^26 N', '9.44 x 10^26 N']
assert audit_options(balanced, 0) == [], audit_options(balanced, 0)
print('PASS 4: four comparable values pass the audit cleanly')

# 5. Unit, kind and giveaway-phrase rules
w = audit_options(['7.55 x 10^26 N', '3.78 x 10^26 N', '12 km/s', 'about ten'], 0)
assert any('different unit' in x for x in w), w
assert any('different kind' in x for x in w), w
w = audit_options(['7.55 x 10^26 N', 'none of the above', '1.89 x 10^26 N',
                   '9.44 x 10^26 N'], 0)
assert any('giveaway phrase' in x for x in w), w
w = audit_options(['7.55 x 10^26 N', '1.89 x 10^26 N', '1.89 x 10^26 N',
                   '9.44 x 10^26 N'], 0)
assert any('duplicate' in x for x in w), w
print('PASS 5: unit, kind, giveaway-phrase and duplicate rules all fire')

# 6. A reworded correct option still grades correct via the index
opts = ['about 7.55 x 10^26 N', '3.78 x 10^26 N', '1.89 x 10^26 N', '9.44 x 10^26 N']
parsed_opts, idx, rats, etypes, warns = parse_option_response(_response(opts, 0), ITEM)
assert idx == 0, idx
assert not rats[0], 'the correct option must carry no rationale'
assert all(rats[1:]), rats
# Text matching alone would fail on a reworded answer...
assert _correct_option_index(opts, '7.55 x 10^26 N') is None
# ...but the index resolves it.
assert _correct_option_index(opts, '7.55 x 10^26 N', idx) == 0
print('PASS 6: reworded correct option grades correct via the index, not text')

# 7. The answer text wins when the model marks the wrong index
swapped = ['3.78 x 10^26 N', '7.55 x 10^26 N', '1.89 x 10^26 N', '9.44 x 10^26 N']
_, idx2, _, _, w2 = parse_option_response(_response(swapped, 0), ITEM)
assert idx2 == 1, idx2
assert any('using the required answer' in x for x in w2), w2
print('PASS 7: a wrong correct_index is corrected to match the required answer')

# 8. Unusable responses are reported, not silently accepted
for bad, why in [('not json', 'prose'), ('{"nope": 1}', 'no options'),
                 ('{"options": "x"}', 'options not a list')]:
    o, i, r, _, w = parse_option_response(bad, ITEM)
    assert o is None, f'{why} should be unusable'
print('PASS 8: unusable responses return None so the item degrades gracefully')

# 9. Hybrid/Theory items are never sent through this stage by the runner; the
#    prompt still marks the reasoning-question exception correctly
reasoning_item = dict(ITEM)
reasoning_item['selected_question'] = dict(ITEM['selected_question'])
reasoning_item['selected_question']['text'] = (
    'Which physical account of the force matches the final readout?')
p = build_option_prompt(reasoning_item, '=== REPORTS ===\nmisconception: X')
assert 'WHICH REASONING is correct' in p or 'reasoning IS the thing' in p, p[-1200:]
p_plain = build_option_prompt(ITEM)
assert 'STATE THE ANSWER' in p_plain
assert 'Do NOT explain or justify it' in p_plain
print('PASS 9: prompt switches to reasoning-mode only for reasoning stems')

# 10. _coerce_index rejects anything that could mis-grade
assert _coerce_index(2) == 2
assert _coerce_index('3') == 3
assert _coerce_index(None) is None
assert _coerce_index(True) is None        # bool is an int subclass
assert _coerce_index(-1) is None
assert _coerce_index('abc') is None
assert _coerce_index(1.5) is None
print('PASS 10: malformed indexes degrade to None instead of mis-grading')

# 11. shuffle carries the index AND the rationales together, for every start
for ci in range(4):
    rats = ['' if i == ci else f'mistake-{i}' for i in range(4)]
    etypes = ['correct' if i == ci else f'error-{i}' for i in range(4)]
    q = GeneratedQuestion(index=0, number=1, q_type='MCQ', section='A',
                          topic='Orbits', question_text='What force?',
                          correct_answer=opts[ci], options=list(opts),
                          correct_option_index=ci, option_rationales=rats,
                          option_error_types=etypes)
    shuffle_mcq_options([q])
    pos = q.correct_option_index
    assert isinstance(pos, int), pos
    # Grading still lands on the right option after the permutation.
    assert _correct_option_index(
        q.options, q.correct_answer, pos
    ) == pos, (ci, q.options, pos)
    # The empty rationale travelled with the correct option.
    assert q.option_rationales[pos] == ''
    # And each distractor kept its own rationale.
    assert all(r for k, r in enumerate(q.option_rationales)
               if k != q.correct_option_index)
    # The error types followed their options too, not the positions.
    assert q.option_error_types[q.correct_option_index] == 'correct'
    assert sorted(q.option_error_types) == sorted(etypes)
print('PASS 11: shuffle permutes options, index, rationales and error types')

# 12. Legacy items with no index still resolve by text/letter
legacy = ['A. 3.78 x 10^26 N', 'B. 7.55 x 10^26 N']
assert _correct_option_index(legacy, 'B. 7.55 x 10^26 N') == 1
assert _correct_option_index(legacy, 'B. 7.55 x 10^26 N', None) == 1
# An out-of-range index must be ignored rather than trusted.
assert _correct_option_index(legacy, 'B. 7.55 x 10^26 N', 99) == 1
assert _correct_option_index(legacy, 'B. 7.55 x 10^26 N', -1) == 1
assert _correct_option_index(legacy, 'B. 7.55 x 10^26 N', True) == 1
print('PASS 12: legacy no-index items fall back to text matching')


# ── 13. error_types are the MODEL's labels, kept verbatim, not a fixed set ────
import json as _json
_types_raw = ['correct', 'doubled the mass term', 'used r instead of r^2',
              'ignored the second body']
_t_opts, _t_i, _t_r, _t_e, _t_w = parse_option_response(
    _json.dumps({'options': opts, 'correct_index': 0, 'rationales': ['', 'a', 'b', 'c'],
                'error_types': _types_raw}), ITEM)
assert _t_e == _types_raw, _t_e
assert _t_e[0] == 'correct'
print('PASS 13: error types are stored verbatim, not mapped to a fixed vocabulary')

# The correct option is recorded as 'correct' even if the model mislabels it.
_, _t_i2, _, _t_e2, _t_w2 = parse_option_response(
    _json.dumps({'options': opts, 'correct_index': 0, 'rationales': ['', 'a', 'b', 'c'],
                'error_types': ['wrong-scaling', 'x', 'y', 'z']}), ITEM)
assert _t_e2[0] == 'correct', _t_e2
assert any('error type' in x for x in _t_w2), _t_w2
print('PASS 14: a mislabelled correct option is corrected to "correct" and warned')

# A short error_types array is padded, never left short.
_, _, _, _t_e3, _t_w3 = parse_option_response(
    _json.dumps({'options': opts, 'correct_index': 0, 'rationales': ['', 'a', 'b', 'c'],
                'error_types': ['correct', 'only-one']}), ITEM)
assert len(_t_e3) == 4, _t_e3
assert _t_e3 == ['correct', 'only-one', '', ''], _t_e3
print('PASS 15: a short error_types array is padded to stay aligned with options')

# A missing error_types array warns rather than silently dropping the labels.
_, _, _, _t_e4, _t_w4 = parse_option_response(
    _json.dumps({'options': opts, 'correct_index': 0, 'rationales': ['', 'a', 'b', 'c']}),
    ITEM)
assert _t_e4 == ['correct', '', '', ''], _t_e4
assert any('error_types' in x for x in _t_w4), _t_w4
print('PASS 16: missing error_types warns and is aligned rather than dropped')

# ── 17. option_warnings reach the compliance audit ───────────────────────────
from main_app.user_selections import check_option_quality

def _seq(**q):
    return {'ordered_quiz_sequence': [{'sequence_index': 1,
            'question': dict({'format': 'Sim', 'text': 'Q', 'options': [],
                              'correct_answer': 'a'}, **q)}]}

assert check_option_quality(_seq()) == []
print('PASS 17a: a clean Sim item reports no option-quality violations')

_w = check_option_quality(_seq(option_warnings=['the CORRECT option is the longest'],
                               options_generated=True))
assert len(_w) == 1 and 'longest' in _w[0] and 'Sim slot 1' in _w[0], _w
print('PASS 17b: a recorded option warning is surfaced with its slot label')

# An item the option agent could not serve must be visible, not silently free.
_w2 = check_option_quality(_seq(options_generated=False,
                                option_warnings=['option agent call failed: timeout']))
assert len(_w2) == 2 and any('free-response' in x for x in _w2), _w2
print('PASS 17c: an option-generation failure is surfaced, not silently degraded')

# Bank-copied MCQs never went through the option generator, so they are skipped.
assert check_option_quality(_seq(format='Non-Sim', options_generated=False)) == []
print('PASS 17d: bank-copied (Non-Sim) items are not reported')

# ── 18. GeneratedQuestion and QuestionRecord both carry the error types ─────
from dataclasses import asdict as _asdict
from main_app.quiz_logger import QuestionRecord as _QR

_gq = GeneratedQuestion(index=0, number=1, q_type='MCQ', section='A', topic='T',
      question_text='Q', correct_answer=opts[0], options=list(opts),
      correct_option_index=0, option_rationales=['', 'a', 'b', 'c'],
      option_error_types=list(_types_raw))
assert _asdict(_gq)['option_error_types'] == _types_raw
assert _asdict(_gq)['option_error_types'] is not _gq.option_error_types
_qr = _QR.from_dict({'index': 0, 'number': 1, 'question': 'Q', 'q_type': 'MCQ',
     'section': 'A', 'is_simulation': True,
     'options': opts, 'correct_answer': opts[0], 'correct_option_index': 0,
     'option_rationales': ['', 'a', 'b', 'c'], 'option_error_types': _types_raw})
assert _asdict(_qr)['option_error_types'] == _types_raw
# A legacy record with no error types must still load.
_legacy_qr = _QR.from_dict({'index': 0, 'number': 1, 'question': 'Q',
      'q_type': 'MCQ', 'section': 'A', 'is_simulation': True,
               'options': opts, 'correct_answer': opts[0]})
assert _legacy_qr.option_error_types == []
print('PASS 18: error types round-trip through GeneratedQuestion and the quiz log')

print('\nAll option-generator tests passed.')
