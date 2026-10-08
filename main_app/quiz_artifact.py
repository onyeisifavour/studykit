"""
quiz_artifact.py

Immutable quiz artifacts. An artifact is a frozen snapshot of a finished quiz's
*content* — never its answers, marks or evaluation. Attempts live elsewhere
(see quiz_instance.py) and reference an artifact by id, so retaking a quiz
many times cannot corrupt it.

Storage:
    ~/.quiz_app/artifacts/<artifact_id>.json
    {
      "artifact_id":           "a1b2c3d4e5f6",
      "created_at":            "2026-09-30T13:00:00",
      "content_sig":           "…16 hex…",
      "source":                "pipeline" | "retake" | "edit" | "duplicate",
      "source_history_quiz_id":"20260911_050443" | null,
      "topics":                ["Physics: Kinematics"],
      "subjects":              ["Physics"],
      "total_questions":       5,
      "questions":             [ …note-shaped entries, run state stripped… ]
    }

artifact_id is derived from the question content, so regenerating an identical
quiz reuses one artifact instead of accumulating near-duplicates. Deriving a
new artifact (edit / duplicate / subset) renumbers 1..N, which changes the
content sig and therefore yields a new id — the parent is left untouched.
"""

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import dashboard_stats
from . import quiz_logger


ARTIFACTS_DIR = Path.home() / '.quiz_app' / 'artifacts'

# Per-question keys that belong to a *run*, not to the quiz content. Stripping
# them is what makes an artifact pristine by construction.
RUN_STATE_KEYS = frozenset({
    'user_choice', 'choice_meta', 'skipped', 'score', 'remark', 'eval',
})

_ARTIFACT_ID_RE = re.compile(r'^[0-9a-f]{12}$')


def _now() -> str:
    return datetime.now().isoformat()


def _path(artifact_id: str) -> Path:
    return ARTIFACTS_DIR / f'{artifact_id}.json'


def _path_validated(artifact_id: Optional[str]) -> Optional[Path]:
    """Path for an already-validated id, or None if the id is malformed."""
    return _path(str(artifact_id)) if is_valid_artifact_id(artifact_id) else None


def is_valid_artifact_id(artifact_id: Optional[str]) -> bool:
    return bool(_ARTIFACT_ID_RE.match(str(artifact_id or '')))


# ── Content helpers ───────────────────────────────────────────────────────────

def content_only(entry: dict) -> dict:
    """A question entry with every run-state key removed."""
    return {k: v for k, v in dict(entry).items() if k not in RUN_STATE_KEYS}


def _sig(entries: list[dict]) -> str:
    """
    Content signature, mirroring quiz_note._questions_sig so an artifact and
    the note it was captured from hash identically.
    """
    parts = [(
        int(e.get('number', 0) or 0),
        str(e.get('type', '') or ''),
        str(e.get('question_text', '') or ''),
        str(e.get('correct_answer', '') or ''),
        list(e.get('options') or []),
    ) for e in entries]
    raw = json.dumps(parts, sort_keys=True, ensure_ascii=False).encode('utf-8')
    return hashlib.sha1(raw).hexdigest()[:16]


def _renumber(entries: list[dict]) -> list[dict]:
    """Sequential 1..N numbering, with index kept in step. Used when deriving."""
    out = []
    for i, e in enumerate(entries):
        c = content_only(e)
        c['index'] = i
        c['number'] = i + 1
        out.append(c)
    return out


def _entry_from_question(q) -> dict:
    """Builds a note-shaped content entry from a GeneratedQuestion."""
    correct = str(getattr(q, 'correct_answer', '') or '').strip()
    return content_only({
        'index':                 int(getattr(q, 'index', 0) or 0),
        'number':                int(getattr(q, 'number', 1) or 1),
        'section':               str(getattr(q, 'section', '') or 'B'),
        'type':                  quiz_type_of(q),
        'format':                'Sim' if getattr(q, 'is_simulation', False) else 'Non-Sim',
        'is_simulation':         bool(getattr(q, 'is_simulation', False)),
        'topic':                 str(getattr(q, 'topic', '') or ''),
        'subject':               str(getattr(q, 'subject', '') or ''),
        'objective_type':        str(getattr(q, 'objective_type', '') or ''),
        'pacing_stage':          str(getattr(q, 'pacing_stage', '') or ''),
        'position_rationale':    str(getattr(q, 'position_rationale', '') or ''),
        'source':                str(getattr(q, 'source', '') or ''),
        'question_text':         str(getattr(q, 'question_text', '') or ''),
        'options':               list(getattr(q, 'options', []) or []),
        'sim_name':              str(getattr(q, 'sim_name', '') or ''),
        'sim_instruction':       str(getattr(q, 'sim_instruction', '') or ''),
        'correct_answer':        correct,
        'correct_answer_present': bool(correct),
    })


def quiz_type_of(q) -> str:
    """Canonical 'MCQ' | 'Hybrid' | 'Theory' — same rule as quiz_note."""
    qt = str(getattr(q, 'quiz_type', '') or '')
    if qt in ('MCQ', 'Hybrid', 'Theory'):
        return qt
    return 'MCQ' if str(getattr(q, 'q_type', '') or '') == 'MCQ' else 'Theory'


def canonical_from_log_type(q_type: Optional[str]) -> str:
    """
    Maps a History log's q_type onto the canonical vocabulary. Logs written by
    the current grader already hold 'MCQ'|'Hybrid'|'Theory'; older ones may
    hold the legacy 'SUBJ'|'SIM', which both mean a written/theory question.
    """
    if quiz_logger.is_local_type(q_type):
        return 'MCQ'
    t = str(q_type or '').strip().upper()
    if t in ('HYBRID', 'THEORY'):
        return 'Hybrid' if t == 'HYBRID' else 'Theory'
    return 'Theory'


# ── CRUD ──────────────────────────────────────────────────────────────────────

def save_artifact(entries: list[dict], *, topics: Optional[list[str]] = None,
                  subjects: Optional[list[str]] = None, source: str = 'pipeline',
                  source_history_quiz_id: Optional[str] = None) -> str:
    """
    Writes an immutable artifact and returns its id. Idempotent: saving the
    same content twice yields the same id and the original created_at.
    """
    content = [content_only(e) for e in entries]
    if not content:
        raise ValueError('An artifact needs at least one question')
    aid = _sig(content)[:12]
    path = _path(aid)
    if path.exists():
        return aid

    topics = list(topics or [])
    subjects = list(subjects or [])
    if not topics:
        topics = list(dict.fromkeys(
            str(e.get('topic', '') or '') for e in content if e.get('topic')))
    if not subjects:
        subjects = list(dict.fromkeys(
            str(e.get('subject', '') or '') for e in content if e.get('subject')))

    record = {
        'artifact_id':            aid,
        'content_sig':            _sig(content),
        'created_at':             _now(),
        'source':                 source,
        'source_history_quiz_id': source_history_quiz_id,
        'topics':                 topics,
        'subjects':               subjects,
        'total_questions':        len(content),
        'questions':              content,
    }
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding='utf-8')
    return aid


def artifact_id_for_sig(content_sig: str) -> Optional[str]:
    """
    The id of the artifact holding this content signature, or None.

    Lets an instance point back at the immutable set it came from without
    carrying a second copy of the question text.
    """
    if not content_sig:
        return None
    aid = str(content_sig)[:12]
    return aid if is_valid_artifact_id(aid) and _path(aid).exists() else None


def load_artifact(artifact_id: str) -> Optional[dict]:
    if not is_valid_artifact_id(artifact_id):
        return None
    path = _path(artifact_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return None


def list_artifacts() -> list[dict]:
    """Summary dicts for every stored artifact, newest first."""
    if not ARTIFACTS_DIR.exists():
        return []
    out = []
    for path in ARTIFACTS_DIR.glob('*.json'):
        try:
            d = json.loads(path.read_text(encoding='utf-8'))
        except Exception:
            continue
        topics = d.get('topics') or []
        out.append({
            'artifact_id':   d.get('artifact_id', path.stem),
            'created_at':    d.get('created_at', ''),
            'source':        d.get('source', ''),
            'topics':        topics,
            'title':         topics[0] if topics else 'Untitled quiz',
            'subject':       (d.get('subjects') or ['Other'])[0],
            'total_questions': d.get('total_questions', len(d.get('questions') or [])),
        })
    out.sort(key=lambda a: a.get('created_at') or '', reverse=True)
    return out


def delete_artifact(artifact_id: Optional[str]) -> bool:
    if not is_valid_artifact_id(artifact_id):
        raise ValueError(f'Invalid artifact id: {artifact_id!r}')
    path = _path_validated(artifact_id)
    if path is None or not path.exists():
        return False
    path.unlink()
    return True


# ── Deriving ──────────────────────────────────────────────────────────────────

def derive_artifact(artifact_id: str, numbers: Optional[list[int]] = None,
                    *, source: str = 'edit') -> str:
    """
    Creates a new, independent artifact from an existing one.

    numbers is the caller's full ordered wish-list of *source* question
    numbers; it drives removal, subsetting and reordering in one argument. The
    result is renumbered 1..N, so it gets its own content-derived id and the
    parent is never modified. numbers=None duplicates everything in order.

    Ids are content-derived, so deriving without changing anything returns the
    parent's id rather than a pointless byte-identical copy. Callers can detect
    this by comparing the result with the id they passed in. Any real edit
    (removal, subset, reorder) changes the sig and yields a new id.
    """
    parent = load_artifact(artifact_id)
    if parent is None:
        raise ValueError(f'No artifact {artifact_id!r}')

    by_number = {int(e.get('number', 0) or 0): e
                 for e in parent.get('questions', [])}
    if numbers is None:
        chosen = [by_number[n] for n in sorted(by_number)]
    else:
        wanted = [int(n) for n in numbers]
        unknown = [n for n in wanted if n not in by_number]
        if unknown:
            raise ValueError(f'Unknown question numbers: {unknown}')
        if not wanted:
            raise ValueError('A derived artifact needs at least one question')
        # A repeated number would silently clone a question into the set.
        repeats = sorted({n for n in wanted if wanted.count(n) > 1})
        if repeats:
            raise ValueError(f'Repeated question numbers: {repeats}')
        chosen = [by_number[n] for n in wanted]

    kept = _renumber(chosen)
    return save_artifact(
        kept,
        topics=list(parent.get('topics') or []),
        subjects=list(parent.get('subjects') or []),
        source=source,
        source_history_quiz_id=parent.get('source_history_quiz_id'),
    )


def artifact_from_questions(questions: list, *, source: str = 'pipeline',
                            topics: Optional[list[str]] = None,
                            subjects: Optional[list[str]] = None) -> str:
    """Captures a freshly assembled quiz as an artifact."""
    return save_artifact(
        [_entry_from_question(q) for q in questions],
        topics=topics, subjects=subjects, source=source,
    )


def artifact_from_note(note: dict, *, source: str = 'pipeline') -> str:
    """Captures an existing quiz note as an artifact."""
    return save_artifact(
        [content_only(e) for e in (note.get('questions') or [])],
        topics=list(note.get('topics') or []),
        subjects=list(note.get('subjects') or []),
        source=source,
    )


def artifact_from_history(quiz_id: str) -> str:
    """
    Builds an artifact from a completed History entry so it can be retaken.
    The log already carries question, options, correct answer, section, topic
    and simulation instruction, which is everything the quiz runtime needs.
    """
    log = quiz_logger.load_quiz_log(quiz_id)
    if log is None:
        raise ValueError(f'No history entry {quiz_id!r}')

    entries = []
    for i, q in enumerate(log.questions):
        correct = str(q.correct_answer or '').strip()
        topic = str(q.topic or '')
        entries.append(content_only({
            'index':                  i,
            'number':                 int(q.number or i + 1),
            'section':                str(q.section or 'B'),
            'type':                   canonical_from_log_type(q.q_type),
            'format':                 'Sim' if q.is_simulation else 'Non-Sim',
            'is_simulation':          bool(q.is_simulation),
            'topic':                  topic,
            'subject':                dashboard_stats._subject_of(topic),
            'objective_type':         '',
            'pacing_stage':           '',
            'position_rationale':     '',
            'source':                 f'history:{quiz_id}',
            'question_text':          str(q.question or ''),
            'options':                list(q.options or []),
            'sim_name':               '',
            'sim_instruction':        str(q.sim_instruction or ''),
            'correct_answer':         correct,
            'correct_answer_present': bool(correct),
        }))

    if not entries:
        raise ValueError(f'History entry {quiz_id!r} has no questions')

    return save_artifact(
        entries,
        topics=list(log.topics or []),
        subjects=list(dict.fromkeys(dashboard_stats._subject_of(t)
                                    for t in (log.topics or []) if t)),
        source='retake',
        source_history_quiz_id=quiz_id,
    )
