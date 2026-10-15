"""
test_tag_parsing.py

Regression tests for question-bank tag parsing and retrieval.

The generation failure this guards against: the tag recognizer rejected the
trailing `Answer-Method` key, so `extract_tags()` returned `{}` for every
question, `build_tag_index` produced blank Type/Format, no search tier matched,
and every slot was flagged MISSING — surfacing as
"The sequencer received an empty selected-items list."

Run: python tests/test_tag_parsing.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from main_app import answer_matcher as am
from main_app import file_retriever as fr


# 1. Question-bank line with the newer Answer-Method key parses all tags.
line = (
    "1. Let $U = \\{1,2,3\\}$. Which set is a subset? "
    "[Type: MCQ; Subject: Maths; Topic: L1.5 Sets; Format: Non-Sim; "
    "Exam: Cambridge IGCSE 0580/22; Answer-Method: text-exclusive]"
)
tags = am.extract_tags(line)
assert tags['Type'] == 'MCQ', tags
assert tags['Subject'] == 'Maths', tags
assert tags['Format'] == 'Non-Sim', tags
assert tags['Answer-Method'] == 'text-exclusive', tags
print('PASS 1: Answer-Method key is recognised')


# 2. Answer-bank form: two adjacent bracket groups.
ab = "1. 7 (neutral pH) [Type: MCQ ] [Answer-Method: text-exclusive]"
tags = am.extract_tags(ab)
assert tags == {'Type': 'MCQ', 'Answer-Method': 'text-exclusive'}, tags
print('PASS 2: two-group answer-bank tags parse')


# 3. strip_tags removes the tag run but preserves a leading bracket marker.
stripped = am.strip_tags(line)
assert 'Answer-Method' not in stripped and '[Type' not in stripped, stripped
assert stripped.startswith('1. Let'), stripped
fig = "[FIGURE: triangle ABC] Find angle A. [Type: Theory; Format: Non-Sim]"
out = am.strip_tags(fig)
assert out == '[FIGURE: triangle ABC] Find angle A.', out
assert am.extract_tags(out) == {}
print('PASS 3: strip_tags removes trailing tags, keeps leading [FIGURE: ...]')


# 4. parse_bank_with_tags yields Type/Format for a maths-style line.
second = ab.replace('1. ', '2. ', 1)
bank = "\n".join([line, "", second])
entries = am.parse_bank_with_tags(bank)
assert len(entries) == 2, entries
assert entries[0]['tags']['Type'] == 'MCQ'
assert entries[0]['tags']['Format'] == 'Non-Sim'
assert entries[0]['question_text'].startswith('Let')
assert entries[1]['tags']['Answer-Method'] == 'text-exclusive'
print('PASS 4: parse_bank_with_tags keeps clean text and tags')


# 5. Negative: content-only trailing brackets are NOT treated as tags.
for content in (
    "6. Solve for x. [2 marks]",
    "7. See the diagram. [Figure 1]",
):
    assert am.extract_tags(content) == {}, content
    assert am.strip_tags(content) == content, content
print('PASS 5: content-only brackets are not stripped')


# 6. End-to-end: a maths-style bank retrieves candidates for a slot.
topic_files = [{
    'subject_name': 'Maths',
    'topic_name': 'L1.5 Sets',
    'questions_text': bank,
    'answers_text': "1. B [Type: MCQ ] [Answer-Method: text-exclusive]",
}]
spec = {
    'file_query_specs': [{
        'slot_number': 1,
        'search_tiers': {
            'tier_1_exact': {
                'subject': 'Maths', 'topic': 'L1.5 Sets',
                'type': 'MCQ', 'format': 'Non-Sim', 'keywords': [],
            },
        },
    }],
}
pool = fr.retrieve_candidates(spec, topic_files)
assert pool[1], 'expected candidates but slot 1 was empty'
assert pool[1][0]['tags']['Type'] == 'MCQ', pool[1][0]['tags']
assert pool[1][0]['answer_text'] == 'B', pool[1][0]
print('PASS 6: retrieve_candidates returns candidates for a tagged slot')


# 7. Guard: banks with questions but no parseable Type/Format fail loudly.
bad_bank = "1. A question with no metadata at the end."
try:
    fr.build_tag_index([{
        'subject_name': 'Maths', 'topic_name': 'X',
        'questions_text': bad_bank, 'answers_text': '',
    }])
except fr.TagIndexError:
    pass
else:
    raise AssertionError('build_tag_index should raise TagIndexError')
print('PASS 7: unparseable bank tags raise TagIndexError')


# 8. Single-line answer banks: every entry on one physical line still parses.
one_line = (
    "1. A [Type: MCQ ] [Answer-Method: text-exclusive]"
    "2. B [Type: MCQ ] [Answer-Method: text-exclusive]"
    "3. $1.36 \\times 10^4$ [Type: Hybrid ] [Answer-Method: text-exclusive]"
)
assert '\n' not in one_line
ans = am.parse_answer_bank(one_line)
assert set(ans) == {1, 2, 3}, ans
assert ans[1] == 'A' and ans[2] == 'B', ans
assert ans[3] == '$1.36 \\times 10^4$', ans
print('PASS 8: single-line answer bank parses every entry')


# 9. Content numbers that are not the next entry must not split an entry.
content = (
    "1. B [Type: MCQ ] [Answer-Method: text-exclusive]"
    "2. (a) $H_0$ holds. (b) df = 3. (c) reject. "
    "[Type: Theory ] [Answer-Method: text-exclusive]"
    "3. C [Type: MCQ ] [Answer-Method: text-exclusive]"
)
ans = am.parse_answer_bank(content)
assert set(ans) == {1, 2, 3}, ans
assert ans[2].startswith('(a) $H_0$ holds.'), ans[2]
assert 'df = 3.' in ans[2], ans[2]
print('PASS 9: stray content numbers do not split an entry')


print('\nAll tag-parsing tests passed.')
