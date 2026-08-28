"""
dashboard_stats.py

Pure functions that compute the /api/dashboard payload from the persisted quiz
logs in ~/.quiz_app/logs. No Tkinter, no I/O beyond reading the log files and
the app config. The Electron renderer consumes this shape verbatim:

    {
      "quizzes": int,
      "questions": int,
      "avg_pct": int,
      "subjects":   [{"name", "pct"}],
      "weak_topics":[{"topic", "pct", "quiz_ids": [...]}],
      "recent":     [{"quiz_id", "created_at", "topics", "completed",
                      "mcq": [correct, total], "written_pct": int|None,
                      "skipped": int}],
      "setup_needed": bool,
    }
"""

import json
import re
from pathlib import Path

from . import config
from . import quiz_logger

WEAK_TOPIC_THRESHOLD_PCT = 60
WEAK_TOPIC_LIMIT = 4
RECENT_LIMIT = 5


# ── Low-level helpers ─────────────────────────────────────────────────────────

def _iter_logs(logs_dir: Path):
    """Yields QuizLog objects from a logs directory, newest file first."""
    if not logs_dir.exists():
        return
    for path in sorted(logs_dir.glob('quiz_*.json'), reverse=True):
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            yield quiz_logger.QuizLog.from_dict(data)
        except Exception:
            continue


def _question_credit(log: quiz_logger.QuizLog, q: quiz_logger.QuestionRecord):
    """
    Returns (credit, weight) for a question on a 0–1 scale, honouring the
    quiz's skip_mode, or None when the question contributes nothing:
        MCQ        → 1.0 if correct else 0.0
        SUBJ/SIM   → the AI score (0–1), omitted if never scored
        skipped    → excluded under 'exclude', else counted as 0
    """
    if q.skipped:
        if log.skip_mode == 'exclude':
            return None
        return 0.0, 1
    if q.q_type == 'MCQ':
        return (1.0 if q.is_correct else 0.0), 1
    if q.q_type in ('SUBJ', 'SIM'):
        if q.score is None:
            return None
        return float(q.score), 1
    return None


# Subject keywords, longest/most-specific first so "SI Units - ..." resolves to
# Physics before the bare "base" in Mathematics can win.
_SUBJECT_KEYWORDS = (
    ('Physics', ('si unit', 'si units', 'physic', 'physical quantit',
                 'dimensional analysis', 'kinematic', 'newton', 'momentum',
                 'wave', 'electr', 'magnet', 'circuit', 'thermo',
                 'measurement', 'derived unit', 'base unit', 'scientific notation')),
    ('Mathematics', ('math', 'algebra', 'calculus', 'geometry', 'trigonometr',
                     'statistic', 'probab', 'number', 'equation', 'function',
                     'graph', 'vector', 'sequence', 'series', 'integral',
                     'derivativ', 'base conversion', 'base determination',
                     'set diagram', 'density proof', 'nested set')),
    ('Chemistry', ('chem', 'acid', 'stoichiometry', 'mole', 'periodic', 'bond',
                   'molecule', 'compound', 'titration', 'reaction')),
    ('Economics', ('econ', 'supply', 'demand', 'market', 'inflation', 'gdp')),
)

# Topics that are leaked folder/file names rather than real quiz content.
_GARBAGE_TOPIC_RE = (
    r'^(topicfolder\d*|untitled|unknown|n/a|new topic)$'
)


def _is_garbage_topic(topic: str) -> bool:
    t = topic.strip()
    if not t:
        return True
    return bool(re.search(_GARBAGE_TOPIC_RE, t, re.IGNORECASE))


def _clean_topic(topic: str) -> str:
    """
    Shortens a topic for display: strips a leading 'Subject (...)' wrapper
    ('Mathematics (Base Conversion)' → 'Base Conversion') but leaves plain
    names like 'Physical Quantities' untouched.
    """
    t = topic.strip()
    m = re.match(r'^[A-Za-z][A-Za-z ]*?\s*\((.+)\)$', t)
    if m:
        return m.group(1).strip() or t
    return t


def _subject_of(topic: str) -> str:
    """
    Maps a quiz topic string to a subject label. Quiz topics arrive with no
    consistent delimiter ('Physics Theory', 'Mathematics (Base Conversion)',
    'Physical Quantities', 'SI Units - Base Units and Redefinition'), so we
    match on subject keywords, then the 'Subject (...)' prefix, then the text
    before any ':', then 'Other'. Never the raw topic itself — that is what
    produced garbage subject rows.
    """
    low = topic.strip().lower()
    if not low:
        return 'Other'
    for label, keys in _SUBJECT_KEYWORDS:
        if any(key in low for key in keys):
            return label
    m = re.match(r'^([A-Za-z][A-Za-z ]*?)\s*\(', topic.strip())
    if m:
        return m.group(1).strip().title()
    if ':' in topic:
        head = topic.split(':', 1)[0].strip()
        return head.title() if head else 'Other'
    return 'Other'


def _question_subject(log: quiz_logger.QuizLog, q: quiz_logger.QuestionRecord) -> str:
    """
    Subject for a question. Falls back to the subject of the quiz's declared
    topics when the question's own topic is unparseable (e.g. 'topicfolder1').
    """
    subject = _subject_of(q.topic)
    if subject != 'Other':
        return subject
    for declared in (log.topics or []):
        subject = _subject_of(declared)
        if subject != 'Other':
            return subject
    return 'Other'


def _group_buckets(logs, key_fn):
    """Accumulates {key: [credit, weight]} across all scored questions."""
    buckets: dict[str, list[float]] = {}
    for log in logs:
        for q in log.questions:
            result = _question_credit(log, q)
            if result is None:
                continue
            credit, weight = result
            key = key_fn(log, q)
            if not key:
                continue
            bucket = buckets.setdefault(key, [0.0, 0])
            bucket[0] += credit
            bucket[1] += weight
    return buckets


def _pct(credit: float, weight: float) -> int:
    return round(credit / weight * 100) if weight else 0


# ── Payload builders ──────────────────────────────────────────────────────────

def build_dashboard(logs_dir: Path | None = None) -> dict:
    logs_dir = Path(logs_dir) if logs_dir is not None else quiz_logger.LOGS_DIR
    logs = list(_iter_logs(logs_dir))

    quizzes = len(logs)
    questions = sum(len(log.questions) for log in logs)

    # Per-quiz overall % (mean across quizzes with any scored questions).
    overalls = []
    for log in logs:
        correct, total = log.mcq_score()
        subj_total, subj_scored = log.subj_score()
        credit = correct + subj_total
        weight = total + subj_scored
        if weight:
            overalls.append(credit / weight * 100)
    avg_pct = round(sum(overalls) / len(overalls)) if overalls else 0

    # Subjects: credit grouped by the subject part of each question topic,
    # most-weighted first.
    subject_buckets = _group_buckets(logs, _question_subject)
    subjects = [
        {'name': name, 'pct': _pct(credit, weight)}
        for name, (credit, weight) in sorted(
            subject_buckets.items(),
            key=lambda kv: kv[1][1],  # weight desc
            reverse=True,
        )
    ]

    # Weak topics: per-topic pct below threshold, weakest first, with the ids
    # of the quizzes that touched them. Garbage topics (leaked folder names)
    # are excluded — their credit still counts toward the subject buckets via
    # the quiz-topic fallback.
    weak_buckets = _group_buckets(
        logs, lambda log, q: None if _is_garbage_topic(q.topic) else _clean_topic(q.topic))
    topic_quiz_ids: dict[str, set] = {}
    for log in logs:
        for q in log.questions:
            if _is_garbage_topic(q.topic):
                continue
            key = _clean_topic(q.topic)
            if key:
                topic_quiz_ids.setdefault(key, set()).add(log.quiz_id)
    weak_topics = []
    for topic, (credit, weight) in weak_buckets.items():
        pct = _pct(credit, weight)
        if pct < WEAK_TOPIC_THRESHOLD_PCT:
            weak_topics.append({
                'topic': topic,
                'pct': pct,
                'quiz_ids': sorted(topic_quiz_ids.get(topic, set())),
            })
    weak_topics.sort(key=lambda w: w['pct'])
    weak_topics = weak_topics[:WEAK_TOPIC_LIMIT]

    # Recent activity, newest first.
    recent = []
    for log in logs[:RECENT_LIMIT]:
        mcq_correct, mcq_total = log.mcq_score()
        subj_total, subj_scored = log.subj_score()
        written_pct = _pct(subj_total, subj_scored) if subj_scored else None
        recent.append({
            'quiz_id': log.quiz_id,
            'created_at': log.created_at,
            'topics': log.topics,
            'completed': log.completed,
            'mcq': [mcq_correct, mcq_total],
            'written_pct': written_pct,
            'skipped': sum(1 for q in log.questions if q.skipped),
        })

    setup_needed = not config.get_selected_topics() and not config.get_library_root()

    return {
        'quizzes': quizzes,
        'questions': questions,
        'avg_pct': avg_pct,
        'subjects': subjects,
        'weak_topics': weak_topics,
        'recent': recent,
        'setup_needed': setup_needed,
    }
