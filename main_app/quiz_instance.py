"""
quiz_instance.py

Mutable attempts ("instances") taken from an immutable artifact.

The separation is deliberate and one-directional:

  artifact  → immutable, content-addressed, never written to after creation.
  instance  → mutable, disposable, holds the student's answers + timing.

An instance is *a working quiz note under a fresh, unique quiz id*, plus an
`instance.json` control plane in `~/.quiz_app/instances/<instance_id>/`.

Doing it this way means every downstream grader keeps working unchanged:
`complete_quiz`, `theory_marker.grade_theory`, `quiz_note.score_profile` and
`quiz_grader._write_quiz_log` all key off `quiz_id` and the standard
`~/.quiz_app/quizzes/<quiz_id>/` note path. The instance store only owns the
things a note cannot express: lifecycle status, position, time entries and the
lineage back to the artifact it was started from.

Timing model
-------------
The clock is server-side so it survives an app restart. `stretch_started_at`
opens a stretch; `save_state` closes it, appends
`{index, elapsed_secs, saved_at}` to `time_entries` and reopens the next one.
Total time is therefore always  sum(time_entries) + the open stretch.

Because a save interrupts the run, an "average time per question" is only
meaningful for a quiz that was never paused. `avg_secs_per_question` refuses to
invent one once any time entry exists and the caller shows the entry log
instead.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import quiz_artifact
from . import quiz_note


INSTANCES_DIR = Path.home() / '.quiz_app' / 'instances'

_INSTANCE_ID_RE = re.compile(r'^i_[0-9a-f]{12}$')

STATUS_CREATED = 'created'
STATUS_ACTIVE = 'active'
STATUS_PAUSED = 'paused'
STATUS_COMPLETED = 'completed'

#: Statuses from which no clock is running. A `created` instance exists and is
#: listed, but the student has not opened the quiz yet, so it has spent no time.
IDLE_STATUSES = frozenset({STATUS_CREATED, STATUS_PAUSED, STATUS_COMPLETED})


# ── Path / id helpers ─────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now().isoformat()


def instance_dir(instance_id: str) -> Path:
    return INSTANCES_DIR / instance_id


def instance_path(instance_id: str) -> Path:
    return instance_dir(instance_id) / 'instance.json'


def is_valid_instance_id(instance_id: Optional[str]) -> bool:
    return bool(_INSTANCE_ID_RE.match(str(instance_id or '')))


def _path_validated(instance_id: Optional[str]) -> Optional[Path]:
    """Path for an already-validated id, or None if the id is malformed."""
    return (instance_path(str(instance_id))
            if is_valid_instance_id(instance_id) else None)


def _require(instance_id: Optional[str]) -> Path:
    path = _path_validated(instance_id)
    if path is None:
        raise ValueError(f'Invalid instance id: {instance_id!r}')
    return path


def _new_instance_id(artifact_id: str, parent: Optional[str]) -> str:
    seed = f'{artifact_id}|{parent or ""}|{_now()}|{len(list(INSTANCES_DIR.glob("*.json")))}'
    digest = hashlib.sha1(seed.encode('utf-8')).hexdigest()[:12]
    return f'i_{digest}'


def _new_work_id(instance_id: str) -> str:
    digest = hashlib.sha1(f'work|{instance_id}'.encode('utf-8')).hexdigest()[:12]
    return f'wi_{digest}'


# ── Load / save ───────────────────────────────────────────────────────────────

def load_instance(instance_id: str) -> Optional[dict]:
    path = _path_validated(instance_id)
    if path is None or not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return None


def save_instance(rec: dict) -> dict:
    path = _require(rec.get('instance_id'))
    rec['updated_at'] = _now()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rec, indent=2, ensure_ascii=False), encoding='utf-8')
    return rec


# ── Timing ────────────────────────────────────────────────────────────────────

def _parse(iso: Optional[str]) -> Optional[datetime]:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(str(iso))
    except Exception:
        return None


def open_stretch_secs(rec: dict, now: Optional[datetime] = None) -> int:
    """Seconds elapsed in the stretch that is currently running, if any."""
    started = _parse(rec.get('stretch_started_at'))
    if started is None:
        return 0
    now = now or datetime.now()
    return max(0, int((now - started).total_seconds()))


def closed_secs(rec: dict) -> int:
    return sum(int(e.get('elapsed_secs', 0) or 0) for e in rec.get('time_entries') or [])


def total_secs(rec: dict, now: Optional[datetime] = None) -> int:
    """Total time spent: every finished stretch plus the one still running."""
    return closed_secs(rec) + open_stretch_secs(rec, now)


def was_paused(rec: dict) -> bool:
    return bool(rec.get('time_entries'))


def avg_secs_per_question(rec: dict, now: Optional[datetime] = None) -> Optional[float]:
    """
    Average seconds per question, or None when the run was paused at least once.

    Pausing splits the total across stretches of unequal length, so the mean is
    no longer a per-question figure. Callers must show the time-entry log in
    that case rather than a number that reads as more precise than it is.
    """
    if was_paused(rec):
        return None
    total_q = int(rec.get('total_questions', 0) or 0)
    if total_q <= 0:
        return None
    total = total_secs(rec, now)
    # An attempt that has not been opened yet has spent no time, and "0.0
    # seconds per question" would read as a real measurement rather than the
    # absence of one.
    if total <= 0:
        return None
    return total / total_q


# ── Work note construction ────────────────────────────────────────────────────

# ── Lifecycle ─────────────────────────────────────────────────────────────────

def _start_from_entries(entries: list[dict], *, topics: Optional[list[str]] = None,
                        subjects: Optional[list[str]] = None,
                        artifact_id: Optional[str] = None) -> dict:
    """Creates an instance around a fresh working note built from `entries`."""
    if not entries:
        raise ValueError('An instance needs at least one question')
    instance_id = _new_instance_id(artifact_id or '', None)
    work_quiz_id = _new_work_id(instance_id)
    topics = list(topics or [])
    subjects = list(subjects or [])
    note = {
        'quiz_id':           work_quiz_id,
        'content_sig':       quiz_artifact._sig(entries),
        'created_at':        _now(),
        'updated_at':        _now(),
        'topics':            topics,
        'subjects':          subjects,
        'total_questions':   len(entries),
        'evaluation_on':     None,
        'skip_mode':         None,
        'sequence_metadata': {},
        'history_written':   False,
        'meta': {
            'instance_id':   instance_id,
            'artifact_id':   artifact_id,
            'origin':        'artifact' if artifact_id else 'branch',
        },
        'questions':         quiz_artifact._renumber(entries),
    }
    quiz_note.save_note(note)
    quiz_note.write_theory_batches(note)
    return save_instance({
        'instance_id':        instance_id,
        'work_quiz_id':       work_quiz_id,
        'artifact_id':        artifact_id,
        'parent_instance_id': None,
        'title':              (topics or ['Untitled quiz'])[0],
        'subject':            (subjects or ['Other'])[0],
        'topics':             topics,
        'created_at':         _now(),
        'status':             STATUS_CREATED,
        'total_questions':    len(note['questions']),
        'current_index':      0,
        'time_entries':       [],
        'stretch_started_at': None,
        'evaluation_on':      None,
        'skip_mode':          None,
        'history_quiz_id':    None,
        'marking_pending':    False,
    })


def start_instance(artifact_id: str) -> dict:
    """
    Begins a new attempt at an artifact. The artifact is only read — the
    student's answers land in a brand new working note.
    """
    artifact = quiz_artifact.load_artifact(artifact_id)
    if artifact is None:
        raise ValueError(f'No such artifact: {artifact_id!r}')
    return _start_from_entries(
        [quiz_artifact.content_only(e) for e in artifact.get('questions') or []],
        topics=artifact.get('topics'), subjects=artifact.get('subjects'),
        artifact_id=artifact.get('artifact_id', artifact_id),
    )


def instance_for_note(quiz_id: str) -> Optional[dict]:
    """The instance already tracking this working note, if there is one."""
    for path in INSTANCES_DIR.glob('*/instance.json') if INSTANCES_DIR.exists() else []:
        try:
            rec = json.loads(path.read_text(encoding='utf-8'))
        except Exception:
            continue
        if isinstance(rec, dict) and rec.get('work_quiz_id') == quiz_id:
            return rec
    return None


def adopt_note(quiz_id: str) -> dict:
    """
    Attaches an instance to a working note that already exists.

    A pipeline-generated quiz already has a note holding the student's answers,
    so there is no reason to copy its content into a fresh one. This records the
    attempt around that note instead, which is also why deleting such an
    instance must not delete the note — it belongs to the original quiz.
    """
    note = quiz_note.load_note(quiz_id)
    if note is None:
        raise ValueError(f'No working note for quiz {quiz_id!r}')

    existing = instance_for_note(quiz_id)
    if existing is not None:
        if existing.get('status') == STATUS_COMPLETED:
            raise ValueError('This quiz is already finished.')
        if existing.get('status') == STATUS_PAUSED:
            return resume_instance(existing['instance_id'])
        return existing

    topics = list(note.get('topics') or [])
    subjects = list(note.get('subjects') or [])
    instance_id = _new_instance_id('', None)
    rec = {
        'instance_id':        instance_id,
        'work_quiz_id':       str(quiz_id),
        'artifact_id':        quiz_artifact.artifact_id_for_sig(
                                  str(note.get('content_sig') or '')),
        'parent_instance_id': None,
        'title':              (topics or ['Untitled quiz'])[0],
        'subject':            (subjects or ['Other'])[0],
        'topics':             topics,
        'created_at':         _now(),
        # Adoption only happens from inside a quiz the student is answering, so
        # creation and opening are the same moment and the clock starts now.
        'status':             STATUS_ACTIVE,
        'total_questions':    int(note.get('total_questions', 0) or 0),
        'current_index':      0,
        'time_entries':       [],
        'stretch_started_at': _now(),
        'evaluation_on':      None,
        'skip_mode':          None,
        'history_quiz_id':    None,
        'marking_pending':    False,
    }
    return save_instance(rec)


def branch_instance(instance_id: str) -> dict:
    """
    Forks the attempt: a new instance from the same artifact with a clean slate,
    leaving the original instance completely untouched.
    """
    rec = load_instance(instance_id)
    if rec is None:
        raise ValueError(f'No such instance: {instance_id!r}')
    artifact_id = rec.get('artifact_id')

    if artifact_id and quiz_artifact.load_artifact(artifact_id) is not None:
        child = start_instance(artifact_id)
    else:
        # Adopted note with no artifact behind it: fork from the note itself.
        note = quiz_note.load_note(str(rec.get('work_quiz_id')))
        if note is None:
            raise ValueError('The quiz content this instance came from is gone.')
        child = _start_from_entries(
            [quiz_artifact.content_only(e) for e in note.get('questions') or []],
            topics=rec.get('topics'),
            subjects=[str(rec.get('subject') or 'Other')],
            artifact_id=artifact_id,
        )
    child['parent_instance_id'] = rec['instance_id']
    child['origin'] = 'branch'
    return save_instance(child)


def save_state(instance_id: str, current_index: Optional[int] = None) -> dict:
    """
    Pauses this instance. Closes the running stretch as one time entry, so the
    total survives a quit and `Resume` can pick up exactly where it left off.
    """
    rec = load_instance(instance_id)
    if rec is None:
        raise ValueError(f'No such instance: {instance_id!r}')
    if rec.get('status') == STATUS_COMPLETED:
        raise ValueError('This quiz is already finished.')
    if current_index is not None:
        rec['current_index'] = max(0, int(current_index))

    # Exactly one entry per save from a running instance. A stretch that
    # measured 0s is still a real save, so it is recorded; saving an already
    # paused instance just updates the position and adds nothing.
    if rec.get('status') == STATUS_ACTIVE:
        rec.setdefault('time_entries', []).append({
            'index':        len(rec.get('time_entries') or []) + 1,
            'elapsed_secs': open_stretch_secs(rec),
            'saved_at':     _now(),
        })
    elif rec.get('status') == STATUS_CREATED:
        # Saved without ever being opened, so there is no stretch to close and
        # no time to bill. It stays unopened rather than becoming a 0s entry.
        return save_instance(rec)
    rec['status'] = STATUS_PAUSED
    rec['stretch_started_at'] = None
    return save_instance(rec)


def resume_instance(instance_id: str) -> dict:
    """Restarts the clock on a paused instance and keeps its position."""
    rec = load_instance(instance_id)
    if rec is None:
        raise ValueError(f'No such instance: {instance_id!r}')
    if rec.get('status') == STATUS_COMPLETED:
        raise ValueError('This quiz is already finished.')
    rec['status'] = STATUS_ACTIVE
    rec['stretch_started_at'] = _now()
    return save_instance(rec)


def open_instance(instance_id: str) -> dict:
    """
    First real contact with the quiz: starts the clock.

    An instance is born `created` with no stretch running, because "Start this
    quiz" and "opening the quiz" are different moments. The student can pick an
    attempt from Artifacts, read it, decide against it and start another, and
    none of that waiting should be billed to the attempt.

    Idempotent: reopening an already-running attempt just returns it, so a
    re-render or a double call cannot restart the clock and lose the stretch.
    """
    rec = load_instance(instance_id)
    if rec is None:
        raise ValueError(f'No such instance: {instance_id!r}')
    if rec.get('status') == STATUS_COMPLETED:
        raise ValueError('This quiz is already finished.')
    if rec.get('status') == STATUS_ACTIVE and rec.get('stretch_started_at'):
        return rec
    rec['status'] = STATUS_ACTIVE
    rec['stretch_started_at'] = _now()
    return save_instance(rec)


def set_position(instance_id: str, current_index: int) -> dict:
    rec = load_instance(instance_id)
    if rec is None:
        raise ValueError(f'No such instance: {instance_id!r}')
    rec['current_index'] = max(0, int(current_index))
    return save_instance(rec)


def finish_instance(instance_id: str, history_quiz_id: str,
                    marking_pending: bool = False) -> dict:
    """Closes the instance against the History entry it produced."""
    rec = load_instance(instance_id)
    if rec is None:
        raise ValueError(f'No such instance: {instance_id!r}')
    if not str(history_quiz_id or '').strip():
        raise ValueError('finish_instance needs the history quiz id.')
    rec['status'] = STATUS_COMPLETED
    rec['stretch_started_at'] = None
    rec['history_quiz_id'] = history_quiz_id
    rec['marking_pending'] = bool(marking_pending)
    return save_instance(rec)


def find_by_history_id(history_quiz_id: str) -> Optional[str]:
    """The instance id whose attempt produced this History entry, if any."""
    if not history_quiz_id or not INSTANCES_DIR.exists():
        return None
    for path in INSTANCES_DIR.glob('*/instance.json'):
        try:
            rec = json.loads(path.read_text(encoding='utf-8'))
        except Exception:
            continue
        if not isinstance(rec, dict):
            continue
        if rec.get('history_quiz_id') == history_quiz_id:
            return str(rec.get('instance_id'))
    return None


def mark_pending_cleared(instance_id: str) -> dict:
    rec = load_instance(instance_id)
    if rec is None:
        raise ValueError(f'No such instance: {instance_id!r}')
    rec['marking_pending'] = False
    return save_instance(rec)


def delete_instance(instance_id: Optional[str]) -> bool:
    path = _path_validated(instance_id)
    if path is None:
        raise ValueError(f'Invalid instance id: {instance_id!r}')
    rec = load_instance(str(instance_id))
    if rec is None:
        return False
    work_id = rec.get('work_quiz_id')
    if work_id and str(work_id).startswith('wi_'):
        shutil.rmtree(quiz_note.note_dir(str(work_id)), ignore_errors=True)
    shutil.rmtree(path.parent, ignore_errors=True)
    return not path.parent.exists()


# ── Answers ───────────────────────────────────────────────────────────────────

def answers_of(instance_id: str) -> list[dict]:
    """
    The instance's answers in the shape `complete_quiz` expects, taken from the
    working note rather than from the renderer.
    """
    rec = load_instance(instance_id)
    if rec is None:
        raise ValueError(f'No such instance: {instance_id!r}')
    note = quiz_note.load_note(str(rec.get('work_quiz_id')))
    if note is None:
        return []
    out = []
    for e in note.get('questions') or []:
        choice = e.get('user_choice')
        out.append({
            'number':      int(e.get('number', 0)),
            'user_choice': choice,
            'choice_meta': e.get('choice_meta'),
            'skipped':     bool(e.get('skipped', False)),
        })
    return out


def note_of(instance_id: str) -> Optional[dict]:
    rec = load_instance(instance_id)
    if rec is None:
        return None
    return quiz_note.load_note(str(rec.get('work_quiz_id')))


# ── Summaries ─────────────────────────────────────────────────────────────────

def summary(rec: dict, now: Optional[datetime] = None) -> dict:
    note = quiz_note.load_note(str(rec.get('work_quiz_id'))) or {}
    answered = sum(
        1 for e in note.get('questions') or []
        if e.get('user_choice') not in (None, '') or e.get('skipped')
    )
    avg = avg_secs_per_question(rec, now)
    return {
        'instance_id':        rec.get('instance_id'),
        'artifact_id':        rec.get('artifact_id'),
        'parent_instance_id': rec.get('parent_instance_id'),
        'title':              rec.get('title') or 'Untitled quiz',
        'subject':            rec.get('subject') or 'Other',
        'topics':             list(rec.get('topics') or []),
        'created_at':         rec.get('created_at', ''),
        'updated_at':         rec.get('updated_at', ''),
        'status':             rec.get('status', STATUS_ACTIVE),
        'total_questions':    int(rec.get('total_questions', 0) or 0),
        'answered':           answered,
        'current_index':      int(rec.get('current_index', 0) or 0),
        'time_entries':       len(rec.get('time_entries') or []),
        'stretch_started_at': rec.get('stretch_started_at'),
        'total_secs':         total_secs(rec, now),
        'avg_secs':           None if avg is None else round(avg, 1),
        'was_paused':         was_paused(rec),
        'work_quiz_id':       rec.get('work_quiz_id'),
        'history_quiz_id':    rec.get('history_quiz_id'),
        'marking_pending':    bool(rec.get('marking_pending', False)),
    }


def list_instances() -> list[dict]:
    """All instances, newest first. A corrupt file is skipped, not fatal."""
    if not INSTANCES_DIR.exists():
        return []
    out = []
    for path in INSTANCES_DIR.glob('*/instance.json'):
        try:
            rec = json.loads(path.read_text(encoding='utf-8'))
        except Exception:
            continue
        if isinstance(rec, dict) and is_valid_instance_id(rec.get('instance_id')):
            out.append(summary(rec))
    out.sort(key=lambda r: str(r.get('created_at', '')), reverse=True)
    return out


def detail(instance_id: str) -> Optional[dict]:
    """The summary plus the indexed time-entry log the renderer shows when paused."""
    rec = load_instance(instance_id)
    if rec is None:
        return None
    out = summary(rec)
    out['entries'] = list(rec.get('time_entries') or [])
    note = note_of(instance_id) or {}
    out['answers'] = [
        {
            'number':      int(e.get('number', 0)),
            'answered':    e.get('user_choice') not in (None, ''),
            'skipped':     bool(e.get('skipped', False)),
        }
        for e in note.get('questions') or []
    ]
    return out
