"""Inline test for the immutable artifact store (main_app.quiz_artifact)."""
import sys
import os
import json
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main_app import quiz_artifact, quiz_logger
from main_app.quiz_logger import QuizLog, QuestionRecord

print('PASS 0: module import')


def load(aid):
    r = quiz_artifact.load_artifact(aid)
    assert r is not None, f'artifact {aid} did not load'
    return r


def entry(n, text, opts=None, topic='Physics: Kinematics', typ='MCQ', ca='A'):
    return {
        'index': n - 1, 'number': n, 'section': 'A' if typ == 'MCQ' else 'B',
        'type': typ, 'format': 'Non-Sim', 'is_simulation': False,
        'topic': topic, 'subject': 'Physics', 'objective_type': '',
        'pacing_stage': '', 'position_rationale': '', 'source': 'pipeline',
        'question_text': text, 'options': list(opts or []), 'sim_name': '',
        'sim_instruction': '', 'correct_answer': ca,
        'correct_answer_present': bool(ca),
        # run-state keys that must NOT survive into the artifact:
        'user_choice': 'B', 'choice_meta': {'kind': 'x'}, 'skipped': True,
        'score': 1.0, 'remark': 'feedback', 'eval': {'note': 'n'},
    }


with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    quiz_artifact.ARTIFACTS_DIR = root / 'artifacts'
    quiz_logger.LOGS_DIR = root / 'logs'

    base = [entry(1, 'Q one', ['A. a', 'B. b']),
            entry(2, 'Q two', ['A. a', 'B. b'], typ='Theory', ca='because'),
            entry(3, 'Q three', ['A. a', 'B. b'])]

    # 1. Saving strips every run-state key
    aid = quiz_artifact.save_artifact(base)
    rec = load(aid)
    for q in rec['questions']:
        for k in quiz_artifact.RUN_STATE_KEYS:
            assert k not in q, f'{k} leaked into artifact'
    assert all(q.get('user_choice') is None for q in rec['questions'])
    print('PASS 1: run state stripped — artifact is pristine')

    # 2. Content is otherwise preserved intact
    kept = {k: v for k, v in base[0].items() if k not in quiz_artifact.RUN_STATE_KEYS}
    assert rec['questions'][0] == kept, rec['questions'][0]
    print('PASS 2: content preserved field-for-field')

    # 3. Id is content-derived and saving again is idempotent
    aid2 = quiz_artifact.save_artifact(base)
    assert aid2 == aid
    assert len(quiz_artifact.list_artifacts()) == 1
    assert rec['created_at'] == load(aid)['created_at']
    print('PASS 3: identical content reuses one artifact')

    # 4. derive(None) duplicates everything, in order, renumbered 1..N
    dup = quiz_artifact.derive_artifact(aid, None, source='duplicate')
    drec = load(dup)
    assert drec['total_questions'] == 3
    assert [q['number'] for q in drec['questions']] == [1, 2, 3]
    assert [q['index'] for q in drec['questions']] == [0, 1, 2]
    assert [q['question_text'] for q in drec['questions']] == \
        ['Q one', 'Q two', 'Q three']
    print('PASS 4: duplicate copies all questions, renumbered')

    # 5. derive(numbers) subsets AND reorders in one argument
    sub = quiz_artifact.derive_artifact(aid, [3, 1], source='edit')
    srec = load(sub)
    assert [q['question_text'] for q in srec['questions']] == ['Q three', 'Q one']
    assert [q['number'] for q in srec['questions']] == [1, 2], 'must renumber 1..N'
    assert srec['source'] == 'edit'
    print('PASS 5: subset + reorder, renumbered, no gaps')

    # 6. The parent is untouched by deriving
    prec = load(aid)
    assert [q['number'] for q in prec['questions']] == [1, 2, 3]
    assert [q['question_text'] for q in prec['questions']] == \
        ['Q one', 'Q two', 'Q three']
    print('PASS 6: parent artifact unchanged by derive')

    # 7. Any real edit yields a distinct id; a no-op duplicate dedups to parent
    #    (ids are content-derived, so an identical set IS the parent).
    assert dup == aid, 'unedited duplicate should dedup to the parent'
    assert sub != aid, 'a real edit must get its own id'
    assert len({aid, dup, sub}) == 2, (aid, dup, sub)
    assert quiz_artifact.derive_artifact(sub, None) == sub
    assert quiz_artifact.derive_artifact(sub, [1, 2]) == sub, 'identity order'
    reordered = quiz_artifact.derive_artifact(sub, [2, 1])
    assert reordered != sub, 'reorder must differ'
    print('PASS 7: edits get new ids; no-op derive dedups to the parent')

    # 8. Bad input is rejected
    for bad, why in (([], 'empty selection'), ([9], 'unknown number'),
                     ([1, 1], 'duplicate number')):
        try:
            quiz_artifact.derive_artifact(aid, bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f'accepted {why}')
    try:
        quiz_artifact.derive_artifact('deadbeefcafe', None)
    except ValueError:
        pass
    else:
        raise AssertionError('derived from a missing artifact')
    print('PASS 8: empty/unknown/duplicate selections and missing parent rejected')

    # 9. list_artifacts summaries
    listing = quiz_artifact.list_artifacts()
    assert {a['artifact_id'] for a in listing} == {aid, sub, reordered}, listing
    assert all({'artifact_id', 'created_at', 'title', 'subject',
                'total_questions'} <= set(a) for a in listing)
    assert listing[0]['title'] == 'Physics: Kinematics'
    dates = [a['created_at'] for a in listing]
    assert dates == sorted(dates, reverse=True), 'not newest-first'
    print('PASS 9: list_artifacts summaries newest-first')

    # 10. delete, and id validation before touching the filesystem
    assert quiz_artifact.delete_artifact(reordered) is True
    assert quiz_artifact.delete_artifact(reordered) is False
    assert {a['artifact_id'] for a in quiz_artifact.list_artifacts()} == {aid, sub}
    for bad in ('../../etc/passwd', '..', 'nothex', None):
        try:
            quiz_artifact.delete_artifact(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f'accepted bad id {bad!r}')
    assert load(aid) is not None
    print('PASS 10: delete works; malformed ids rejected')

    # 11. History -> artifact round trip (the retake path)
    log = QuizLog(quiz_id='20260924_131830', created_at='2026-01-01T00:00:00',
                  topics=['Physics: Universal Gravitation'], skip_mode='zero')
    log.questions = [
        QuestionRecord(index=0, number=1, question='What is F?',
                       section='A', q_type='MCQ', is_simulation=False,
                       correct_answer='B', options=['A. x', 'B. y'],
                       user_answer='B', is_correct=True, topic='Physics: Gravitation'),
        QuestionRecord(index=1, number=2, question='Explain gravity.',
                       section='B', q_type='Theory', is_simulation=False,
                       correct_answer='attraction', options=[],
                       user_answer='pulls', score=0.8, ai_feedback='ok',
                       topic='Physics: Gravitation', sim_instruction='read this'),
    ]
    quiz_logger.save_quiz_log(log)

    raid = quiz_artifact.artifact_from_history('20260924_131830')
    rrec = load(raid)
    assert rrec['source'] == 'retake'
    assert rrec['source_history_quiz_id'] == '20260924_131830'
    assert rrec['total_questions'] == 2
    types = [q['type'] for q in rrec['questions']]
    assert types == ['MCQ', 'Theory'], types
    assert rrec['questions'][1]['sim_instruction'] == 'read this'
    assert rrec['questions'][0]['correct_answer'] == 'B'
    assert rrec['questions'][1]['correct_answer'] == 'attraction'
    assert rrec['questions'][0]['options'] == ['A. x', 'B. y']
    for q in rrec['questions']:
        for k in quiz_artifact.RUN_STATE_KEYS:
            assert k not in q
    print('PASS 11: History entry becomes a clean, run-state-free artifact')

    # 12. A retake artifact is a normal artifact — derivable and retakeable
    again = quiz_artifact.derive_artifact(raid, [2], source='edit')
    arec = load(again)
    assert arec['total_questions'] == 1
    assert arec['questions'][0]['question_text'] == 'Explain gravity.'
    assert arec['questions'][0]['number'] == 1
    print('PASS 12: a retake artifact can itself be edited into a subset')

    # 13. Legacy log vocabularies map onto canonical types
    assert quiz_artifact.canonical_from_log_type('SUBJ') == 'Theory'
    assert quiz_artifact.canonical_from_log_type('SIM') == 'Theory'
    assert quiz_artifact.canonical_from_log_type('Hybrid') == 'Hybrid'
    assert quiz_artifact.canonical_from_log_type('MCQ') == 'MCQ'
    assert quiz_artifact.canonical_from_log_type(None) == 'Theory'
    print('PASS 13: legacy SUBJ/SIM log types map to Theory')

print('\nAll artifact tests passed.')
