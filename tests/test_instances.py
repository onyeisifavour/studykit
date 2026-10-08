"""Isolated tests for the instance store: lifecycle, timing, immutability."""

import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_TMP = Path(tempfile.mkdtemp(prefix='quiz-inst-test-'))
os.environ['HOME'] = str(_TMP)
os.environ['XDG_CONFIG_HOME'] = str(_TMP / '.config')

for _m in [m for m in list(sys.modules) if m.startswith('main_app')]:
    del sys.modules[_m]

from main_app import config, quiz_artifact, quiz_instance, quiz_logger, quiz_note

PASS, FAIL = 0, 0


def check(label, cond, extra=''):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f'PASS {label}')
    else:
        FAIL += 1
        print(f'FAIL {label} {extra}')


def cleanup():
    shutil.rmtree(_TMP, ignore_errors=True)


def _raises(fn):
    try:
        fn()
    except ValueError:
        return True
    return False


def make_artifact(n=3):
    return quiz_artifact.save_artifact([
        {'number': i + 1, 'index': i, 'section': 'B', 'type': 'MCQ',
         'question_text': f'Q{i + 1} text', 'options': ['A. a', 'B. b', 'C. c', 'D. d'],
         'correct_answer': 'A', 'topic': 'T', 'is_simulation': False}
        for i in range(n)
    ])


try:
    # 1. Starting an instance does not touch the artifact
    aid = make_artifact()
    before = Path(quiz_artifact._path(aid)).read_text()
    raw = quiz_instance.start_instance(aid)
    iid = raw['instance_id']
    inst = quiz_instance.summary(raw)
    after = Path(quiz_artifact._path(aid)).read_text()
    check('starting an instance leaves the artifact byte-identical', before == after)
    check('instance is validly named', quiz_instance.is_valid_instance_id(iid))
    check('work note has a fresh id', str(raw['work_quiz_id']).startswith('wi_'))
    # 1b. First-open timing: choosing an attempt is not the same as opening it.
    check('a new attempt starts unopened', inst['status'] == quiz_instance.STATUS_CREATED)
    check('an unopened attempt has no stretch', inst['stretch_started_at'] is None)
    check('an unopened attempt has spent no time', inst['total_secs'] == 0)
    check('an unopened attempt has no average', inst['avg_secs'] is None)

    # 2. The working note mirrors the content and starts blank
    note = quiz_instance.note_of(iid)
    check('work note exists', note is not None)
    check('work note has all questions', len(note['questions']) == 3)
    check('answers start empty', inst['answered'] == 0)
    check('work note holds no answers',
          all(e.get('user_choice') is None for e in note['questions']))
    check('work note is not the artifact id',
          note['quiz_id'] != aid)

    # 3. Opening the quiz is what starts the clock, and it is idempotent.
    check('saving an unopened attempt does not start or bill a clock',
          quiz_instance.save_state(iid, current_index=1)['status']
          == quiz_instance.STATUS_CREATED)
    check('that save added no time entry', len(quiz_instance.detail(iid)['entries']) == 0)
    opened = quiz_instance.open_instance(iid)
    check('opening makes it active', opened['status'] == quiz_instance.STATUS_ACTIVE)
    check('opening starts a stretch', bool(opened['stretch_started_at']))
    first_stretch = opened['stretch_started_at']
    again = quiz_instance.open_instance(iid)
    check('opening again keeps the same stretch',
          again['stretch_started_at'] == first_stretch)
    check('reopening did not restart the clock',
          quiz_instance.total_secs(again) <= 1, f"t={quiz_instance.total_secs(again)}")

    # 4. Timing: a never-paused run has a valid average
    rec = quiz_instance.load_instance(iid)
    check('no time entries yet', quiz_instance.was_paused(rec) is False)
    # simulate 60s elapsed by rewinding the stretch
    from datetime import datetime, timedelta
    rec['stretch_started_at'] = (
        datetime.fromisoformat(rec['stretch_started_at']) - timedelta(seconds=60)
    ).isoformat()
    quiz_instance.save_instance(rec)
    total = quiz_instance.total_secs(rec)
    check('total time counts the open stretch', 59 <= total <= 61, f'total={total}')
    avg = quiz_instance.avg_secs_per_question(rec)
    check('never-paused run has an average', avg is not None and 19 <= avg <= 21, f'avg={avg}')

    # 4. Save State closes the stretch as a time entry
    quiz_instance.save_state(iid, current_index=2)
    saved = quiz_instance.detail(iid)
    check('save pauses the instance', saved['status'] == quiz_instance.STATUS_PAUSED)
    check('save records one entry', len(saved['entries']) == 1)
    e = saved['entries'][0]
    check('entry is indexed from 1', e['index'] == 1)
    check('entry carries the stretch', 59 <= e['elapsed_secs'] <= 61, f"elapsed={e['elapsed_secs']}")
    check('entry is timestamped', bool(e.get('saved_at')))
    check('save stops the clock', saved['total_secs'] == e['elapsed_secs'])
    check('save keeps the position', saved['current_index'] == 2)

    # 5. A paused run refuses an average and exposes the log instead
    check('paused run has no average', quiz_instance.avg_secs_per_question(saved) is None)
    check('detail exposes the entry log', len(saved['entries']) == 1)
    check('summary flags the pause', saved['was_paused'] is True)
    check('summary average is null', saved['avg_secs'] is None)
    check('detail reports the answer map', len(saved['answers']) == 3)

    # 6. Total does not advance while paused, then accrues on Resume
    check('total frozen while paused',
          quiz_instance.total_secs(quiz_instance.load_instance(iid)) == saved['total_secs'])
    quiz_instance.resume_instance(iid)
    resumed = quiz_instance.detail(iid)
    check('resume reactivates', resumed['status'] == quiz_instance.STATUS_ACTIVE)
    check('resume adds no entry', len(resumed['entries']) == 1)
    check('resume keeps the position', resumed['current_index'] == 2)

    # 7. Saves accumulate; total is always the sum of every entry
    def rewind_open_stretch(instance_id, secs):
        """Resumes, then rewinds the fresh stretch so it measures `secs`."""
        rec = quiz_instance.resume_instance(instance_id)
        rec['stretch_started_at'] = (
            datetime.fromisoformat(rec['stretch_started_at']) - timedelta(seconds=secs)
        ).isoformat()
        return quiz_instance.save_instance(rec)

    quiz_instance.save_state(iid, current_index=3)          # entry 2 (near 0s)
    rewind_open_stretch(iid, 30)
    quiz_instance.save_state(iid)                           # entry 3 (30s)
    three = quiz_instance.detail(iid)
    check('each save adds one entry', len(three['entries']) == 3)
    check('entries are indexed 1,2,3', [e['index'] for e in three['entries']] == [1, 2, 3])
    check('total is the sum of all entries',
          three['total_secs'] == sum(e['elapsed_secs'] for e in three['entries']))
    check('the 30s stretch was recorded', three['entries'][2]['elapsed_secs'] >= 29)
    check('still no average after many pauses', three['avg_secs'] is None)

    # Saving an already-paused instance must not invent an extra entry.
    quiz_instance.save_state(iid, current_index=4)
    again = quiz_instance.detail(iid)
    check('saving while paused adds no entry', len(again['entries']) == 3)
    check('saving while paused still moves position', again['current_index'] == 4)

    # 8. Branch: same content, clean slate, original untouched
    orig_before = Path(quiz_instance.instance_path(iid)).read_text()
    child_rec = quiz_instance.branch_instance(iid)
    bid = child_rec['instance_id']
    branch = quiz_instance.detail(bid)
    check('branch gets its own id', bid != iid)
    check('branch records its parent', branch['parent_instance_id'] == iid)
    check('branch points at the same artifact', branch['artifact_id'] == aid)
    check('branch has no answers', branch['answered'] == 0)
    check('branch has no time entries', branch['time_entries'] == 0 and not branch['entries'])
    check('branch has the same question count',
          branch['total_questions'] == three['total_questions'])
    check('original instance is untouched',
          Path(quiz_instance.instance_path(iid)).read_text() == orig_before)
    bnote = quiz_instance.note_of(bid)
    check('branch note is blank', all(e.get('user_choice') is None
                                      for e in bnote['questions']))
    check('branch note is a separate file',
          bnote['quiz_id'] != quiz_instance.note_of(iid)['quiz_id'])

    # 9. Answers round-trip in the shape complete_quiz expects
    quiz_note.set_user_choice(quiz_instance.load_instance(iid)['work_quiz_id'], 1,
                              'A. a', {'kind': 'option', 'index': 0})
    quiz_note.set_user_choice(quiz_instance.load_instance(iid)['work_quiz_id'], 2, None, None,
                              skipped=True)
    ans = quiz_instance.answers_of(iid)
    check('answers cover every question', len(ans) == 3)
    check('answer carries number/choice/meta', ans[0]['number'] == 1
          and ans[0]['user_choice'] == 'A. a'
          and ans[0]['choice_meta'] == {'kind': 'option', 'index': 0})
    check('skipped flag is preserved', ans[1]['skipped'] is True)
    check('answered count reflects the note', quiz_instance.detail(iid)['answered'] == 2)

    # 10. Finish links the History entry and blocks further saves
    quiz_logger.save_quiz_log(quiz_logger.new_quiz_log(topics=['T']))
    hist_id = quiz_logger.list_quiz_logs()[0]['quiz_id']
    quiz_instance.finish_instance(iid, hist_id, marking_pending=True)
    done = quiz_instance.detail(iid)
    check('finish completes the instance', done['status'] == quiz_instance.STATUS_COMPLETED)
    check('finish records the history id', done['history_quiz_id'] == hist_id)
    check('finish records pending marking', done['marking_pending'] is True)
    try:
        quiz_instance.save_state(iid)
        check('finished instance refuses Save State', False, 'no error raised')
    except ValueError:
        check('finished instance refuses Save State', True)
    try:
        quiz_instance.resume_instance(iid)
        check('finished instance refuses Resume', False, 'no error raised')
    except ValueError:
        check('finished instance refuses Resume', True)

    # 11. list_instances is newest-first and includes every instance
    ids = [r['instance_id'] for r in quiz_instance.list_instances()]
    check('both instances listed', set(ids) == {iid, bid})
    dates = [r['created_at'] for r in quiz_instance.list_instances()]
    check('newest first', dates == sorted(dates, reverse=True))

    # 12. Delete removes the instance and its working note
    work_dir = quiz_instance.note_of(bid)['quiz_id']
    work_path = quiz_note.note_dir(work_dir)
    check('delete reports success', quiz_instance.delete_instance(bid) is True)
    check('delete removes the record', quiz_instance.load_instance(bid) is None)
    check('delete removes the working note', not work_path.exists())
    check('delete twice reports False', quiz_instance.delete_instance(bid) is False)

    # 13. Malformed ids are rejected before touching the filesystem
    for bad in ('../../etc/passwd', '..', 'i_ZZZZ', 'nothex', '', None):
        try:
            quiz_instance.delete_instance(bad)
            check(f'rejects bad id {bad!r}', False, 'no error')
        except ValueError:
            check(f'rejects bad id {bad!r}', True)

    for bad in ('deadbeefcafe', 'i_000000000000'):
        try:
            quiz_instance.start_instance(bad)
            check(f'rejects missing artifact {bad!r}', False, 'no error')
        except ValueError:
            check(f'rejects missing artifact {bad!r}', True)

    # 14. Branching survives losing the artifact by falling back to the note,
    #     and is only refused when the content is gone from both places.
    orphan = quiz_instance.start_instance(aid)
    quiz_artifact.delete_artifact(aid)
    still = quiz_instance.branch_instance(orphan['instance_id'])
    still_det = quiz_instance.detail(still['instance_id'])
    check('branch falls back to the note when the artifact is gone',
          still_det is not None and still_det['total_questions'] == 3)
    check('fallback branch is blank', still_det['answered'] == 0)
    check('fallback branch notes the missing artifact',
          still['artifact_id'] == aid)

    shutil.rmtree(quiz_note.note_dir(still['work_quiz_id']), ignore_errors=True)
    check('branch is refused once the content is gone from everywhere',
          _raises(lambda: quiz_instance.branch_instance(still['instance_id'])))

    # 15. Content that was never touched is never written into an artifact
    check('artifact store writes no run state',
          all(not (quiz_artifact.RUN_STATE_KEYS & set(e))
              for a in quiz_artifact.list_artifacts()
              for e in quiz_artifact.load_artifact(a['artifact_id'])['questions']))

    # 16. adopt_note wraps a note that already exists (the pipeline path)
    note_id = 'adhoc_quiz_id'
    note = {
        'quiz_id': note_id, 'content_sig': 'adhocsig', 'created_at': 'now',
        'updated_at': 'now', 'topics': ['Adopted'], 'subjects': ['Biology'],
        'total_questions': 2, 'evaluation_on': None, 'skip_mode': None,
        'sequence_metadata': {}, 'history_written': False, 'meta': {},
        'questions': [
            {'index': 0, 'number': 1, 'section': 'B', 'type': 'MCQ',
             'question_text': 'adopted one', 'options': ['A. a', 'B. b'],
             'correct_answer': 'A', 'topic': 'Adopted', 'user_choice': 'A. a',
             'skipped': False, 'score': None},
            {'index': 1, 'number': 2, 'section': 'B', 'type': 'MCQ',
             'question_text': 'adopted two', 'options': ['A. a', 'B. b'],
             'correct_answer': 'B', 'topic': 'Adopted', 'user_choice': None,
             'skipped': False, 'score': None},
        ],
    }
    quiz_note.save_note(note)
    adopted_rec = quiz_instance.adopt_note(note_id)
    aid2 = adopted_rec['instance_id']
    adopted = quiz_instance.detail(aid2)
    check('adopt keeps the existing note id',
          adopted_rec['work_quiz_id'] == note_id)
    check('adopt finds the existing answer', adopted['answered'] == 1)
    check('adopt links no artifact when the sig is unknown',
          adopted['artifact_id'] is None)
    check('adopt is idempotent',
          quiz_instance.adopt_note(note_id)['instance_id'] == aid2)
    check('adopt is idempotent after the first',
          len([r for r in quiz_instance.list_instances()
               if r['instance_id'] == aid2]) == 1)

    # The adopted note must survive deleting its instance: it is the real quiz.
    check('adopted instance can be deleted', quiz_instance.delete_instance(aid2) is True)
    check('adopted note survives the delete', quiz_note.load_note(note_id) is not None)
    check('adopted note keeps its answers',
          quiz_note.load_note(note_id)['questions'][0]['user_choice'] == 'A. a')

    # 17. Branching an adopted instance with no artifact forks from the note
    adopted2 = quiz_instance.adopt_note(note_id)
    fork = quiz_instance.branch_instance(adopted2['instance_id'])
    fork_det = quiz_instance.detail(fork['instance_id'])
    check('adopted instance can branch', fork is not None)
    check('branch without an artifact still works', fork_det is not None)
    check('branch copy is a new note',
          fork['work_quiz_id'] != note_id)
    check('branch copy is blank', fork_det['answered'] == 0)
    check('branch copy has the same questions',
          fork_det['total_questions'] == 2)
    fnote = quiz_instance.note_of(fork['instance_id'])
    check('branch copy content matches',
          [q['question_text'] for q in fnote['questions']]
          == ['adopted one', 'adopted two'])
    check('branch copy numbers are 1..N',
          [q['number'] for q in fnote['questions']] == [1, 2])
    check('branch copy carries no answers',
          all(q.get('user_choice') is None for q in fnote['questions']))
    check('adopt on a missing note is rejected',
          _raises(lambda: quiz_instance.adopt_note('nope_not_a_note')))

    # A completed attempt must not be silently re-adopted and un-paused.
    quiz_logger.save_quiz_log(quiz_logger.new_quiz_log(topics=['Adopted']))
    hid = quiz_logger.list_quiz_logs()[0]['quiz_id']
    quiz_instance.finish_instance(fork['instance_id'], hid)
    check('adopt on a completed quiz is rejected',
          _raises(lambda: quiz_instance.adopt_note(fork['work_quiz_id'])))

    print(f'\n{PASS} passed, {FAIL} failed')
    sys.exit(1 if FAIL else 0)
finally:
    cleanup()
