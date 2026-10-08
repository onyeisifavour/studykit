"""
quiz_logger.py

Creates and updates persistent quiz log files.
Each quiz gets one JSON file in ~/.quiz_app/logs/

File structure:
    quiz_20250712_143022.json
    {
      "quiz_id":        "20250712_143022",
      "created_at":     "2025-07-12T14:30:22",
      "topics":         ["Physics: Newton's Laws", "Chemistry: Acids"],
      "evaluation_on":  true,
      "completed":      false,
      "summary_report": "",
      "questions": [
        {
          "index":         0,
          "number":        1,
          "question":      "What is ...",
          "section":       "A",
          "q_type":        "MCQ",
          "is_simulation": false,
          "correct_answer":"B",
          "options":       ["A. ...", "B. ...", "C. ...", "D. ..."],
          "user_answer":   "B",
          "is_correct":    true,
          "score":         null,
          "ai_feedback":   "",
          "topic":         "Physics: Newton's Laws"
        },
        ...
      ]
    }
"""

import json
import os
import re
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional


LOGS_DIR = Path.home() / '.quiz_app' / 'logs'


# ── Question-type vocabulary ───────────────────────────────────────────────────
# Two vocabularies describe the same field. Quiz notes record the pipeline's
# 'MCQ' | 'Hybrid' | 'Theory'; the log-level schema and older call sites use
# 'SUBJ' | 'SIM'. Stats must never drop a type they fail to recognise, so every
# type check goes through these predicates instead of comparing literals.

LOCAL_TYPES = frozenset({'MCQ'})
AI_TYPES = frozenset({'SUBJ', 'THEORY', 'HYBRID', 'SIM'})


def _norm_type(q_type: Optional[str]) -> str:
    return str(q_type or '').strip().upper()


def is_local_type(q_type: Optional[str]) -> bool:
    """True when the question is marked locally against a fixed answer key."""
    return _norm_type(q_type) in LOCAL_TYPES


def is_ai_type(q_type: Optional[str]) -> bool:
    """True when the question needs an AI score rather than a local key check."""
    return _norm_type(q_type) in AI_TYPES


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class QuestionRecord:
    index:         int
    number:        int            # 1-based display number
    question:      str
    section:       str            # 'A' or 'B'
    q_type:        str            # 'MCQ', 'SUBJ', 'SIM'
    is_simulation: bool
    correct_answer:str
    options:       list[str]      = field(default_factory=list)

    # Authoritative correct-option position, set by the sim option generator so
    # grading does not depend on matching reworded option text. None for
    # bank-copied and legacy entries, which fall back to text matching.
    correct_option_index: Optional[int] = None

    # Per-option "you likely <mistake>" explanations, aligned to `options`.
    # Recorded for later feedback/analytics; not shown in the quiz UI yet.
    option_rationales:   list[str]      = field(default_factory=list)

    # Per-option short label for the mistake the option encodes, aligned to
    # `options`; the correct option is 'correct'. The option agent picks these
    # labels itself, so they are free text rather than a fixed vocabulary.
    option_error_types:  list[str]      = field(default_factory=list)

    user_answer:   str            = ''
    is_correct:    Optional[bool] = None   # MCQ local marking
    score:         Optional[float]= None   # Section B AI score (0–1)
    ai_feedback:   str            = ''
    topic:         str            = ''
    sim_instruction: str          = ''     # simulation pre-question instruction
    skipped:       bool           = False  # user hit Skip rather than answering

    @classmethod
    def from_dict(cls, d: dict) -> 'QuestionRecord':
        """Builds a record, ignoring keys this version doesn't know about."""
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in dict(d).items() if k in known})


@dataclass
class QuizLog:
    quiz_id:        str
    created_at:     str
    topics:         list[str]
    evaluation_on:  bool                        = True
    skip_mode:      str                         = 'zero'   # 'zero' | 'exclude' — chosen at quiz start
    completed:      bool                        = False
    summary_report: str                         = ''
    # True when the student chose "Mark later": subjective scores are not in the
    # log yet, so the UI shows a pending badge instead of a real percentage.
    marking_pending: bool                       = False
    # The working note this log was built from. Usually equal to quiz_id, but an
    # instance logs under a fresh timestamp id while its note keeps its own
    # work id — deferred marking needs the note, so it is recorded here.
    source_quiz_id: Optional[str]               = None
    questions:      list[QuestionRecord]        = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> 'QuizLog':
        # Copy first: the old version popped straight out of the caller's dict.
        data = dict(d)
        raw_questions = data.pop('questions', [])
        known = set(cls.__dataclass_fields__)
        obj = cls(**{k: v for k, v in data.items() if k in known})
        obj.questions = [QuestionRecord.from_dict(q) for q in raw_questions]
        return obj

    # ── Derived stats ──────────────────────────────────────────────────────────

    def mcq_score(self) -> tuple[int, int]:
        """Returns (correct_count, total_mcq), respecting skip_mode."""
        mcq = [q for q in self.questions if is_local_type(q.q_type)]
        if self.skip_mode == 'exclude':
            mcq = [q for q in mcq if not q.skipped]
        correct = sum(1 for q in mcq if q.is_correct and not q.skipped)
        return correct, len(mcq)

    def subj_score(self) -> tuple[float, int]:
        """Returns (total_score_sum, total_subj_questions_scored), respecting skip_mode."""
        subj = [q for q in self.questions if is_ai_type(q.q_type)]
        if self.skip_mode == 'exclude':
            subj = [q for q in subj if not q.skipped]
        # Under 'zero' mode a skipped question counts as a 0 even though it
        # was never actually scored by the AI — under 'exclude' it's already
        # been filtered out above, so this just catches genuinely-scored ones.
        scored = [q for q in subj if q.score is not None or q.skipped]
        total = sum((q.score or 0.0) for q in scored)
        return total, len(scored)


# ── CRUD ──────────────────────────────────────────────────────────────────────

def _free_quiz_id() -> str:
    """
    A History id that no other log can claim, and that is claimed the moment it
    is handed out.

    The timestamp only resolves to the second, so generating two quizzes in the
    same second would otherwise reuse one id and the second save would silently
    overwrite the first quiz's answers. The append-only probe below therefore
    *reserves* the id by creating the file, rather than merely testing for it:
    an id that exists only in memory is still free to a second caller, which is
    exactly the race this is here to close.

    `_2`, `_3`, ... keep the readable timestamp prefix.
    """
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    for suffix in range(1, 1000):
        candidate = stamp if suffix == 1 else f'{stamp}_{suffix}'
        try:
            # 'x' fails if the file exists, so exactly one caller can create it.
            fd = os.open(LOGS_DIR / f'quiz_{candidate}.json',
                         os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            continue
        except FileNotFoundError:
            LOGS_DIR.mkdir(parents=True, exist_ok=True)
            continue
        os.close(fd)
        return candidate
    raise RuntimeError('Could not allocate a free quiz id.')


def new_quiz_log(topics: list[str], evaluation_on: bool = True, skip_mode: str = 'zero') -> QuizLog:
    log = QuizLog(
        quiz_id=_free_quiz_id(),
        created_at=datetime.now().isoformat(),
        topics=topics,
        evaluation_on=evaluation_on,
        skip_mode=skip_mode,
    )
    # Write the empty log straight away so the id is durably reserved before any
    # answer is recorded. The caller's later save_quiz_log fills it in.
    save_quiz_log(log)
    return log


def save_quiz_log(log: QuizLog) -> Path:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    path = LOGS_DIR / f'quiz_{log.quiz_id}.json'
    path.write_text(json.dumps(log.to_dict(), indent=2), encoding='utf-8')
    return path


def load_quiz_log(quiz_id: str) -> Optional[QuizLog]:
    path = LOGS_DIR / f'quiz_{quiz_id}.json'
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return QuizLog.from_dict(data)
    except Exception:
        return None


def list_quiz_logs() -> list[dict]:
    """
    Returns summary dicts for all saved quizzes, newest first.
    Each dict: {quiz_id, created_at, topics, completed, path}
    """
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    summaries = []
    for path in sorted(LOGS_DIR.glob('quiz_*.json'), reverse=True):
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            summaries.append({
                'quiz_id':    data['quiz_id'],
                'created_at': data['created_at'],
                'topics':     data.get('topics', []),
                'completed':  data.get('completed', False),
                'marking_pending': bool(data.get('marking_pending', False)),
                'path':       str(path),
            })
        except Exception:
            continue
    return summaries


# quiz_id becomes part of a filesystem path, so it is validated before use.
_QUIZ_ID_RE = re.compile(r'^\d{8}_\d{6}(?:_\d+)?$')


def is_valid_quiz_id(quiz_id: Optional[str]) -> bool:
    return bool(_QUIZ_ID_RE.match(str(quiz_id or '')))


def delete_quiz_log(quiz_id: Optional[str]) -> bool:
    """
    Deletes one saved quiz's log file. Returns True when a file was removed,
    False when there was nothing to remove. Raises ValueError on a malformed
    id rather than letting it reach the filesystem.
    """
    if not is_valid_quiz_id(quiz_id):
        raise ValueError(f'Invalid quiz id: {quiz_id!r}')
    path = LOGS_DIR / f'quiz_{quiz_id}.json'
    if not path.exists():
        return False
    path.unlink()
    return True


# ── Update helpers ────────────────────────────────────────────────────────────

def add_question(log: QuizLog, record: QuestionRecord) -> None:
    """Appends a question record to the log and persists."""
    log.questions.append(record)
    save_quiz_log(log)


def update_answer(
    log: QuizLog,
    index: int,
    user_answer: str,
    *,
    is_correct:  Optional[bool]  = None,
    score:       Optional[float] = None,
    ai_feedback: str             = '',
) -> None:
    """Updates a question record with the user's answer/evaluation and persists."""
    for q in log.questions:
        if q.index == index:
            q.user_answer = user_answer
            if is_correct is not None:
                q.is_correct = is_correct
            if score is not None:
                q.score = score
            if ai_feedback:
                q.ai_feedback = ai_feedback
            break
    save_quiz_log(log)


def mark_complete(log: QuizLog, summary: str = '') -> None:
    log.completed = True
    if summary:
        log.summary_report = summary
    save_quiz_log(log)


def mark_skipped(log: QuizLog, index: int) -> None:
    """Marks a question as skipped rather than answered, and persists."""
    for q in log.questions:
        if q.index == index:
            q.skipped = True
            q.user_answer = '(skipped)'
            break
    save_quiz_log(log)


# ── Session-data formatter (for summary API call) ─────────────────────────────

def format_for_summary(log: QuizLog) -> str:
    """Serialises quiz log into a plain-text block for the summary prompt."""
    lines = [f"Quiz — {log.created_at}", f"Topics: {', '.join(log.topics)}", '']

    for q in log.questions:
        lines.append(f"--- Question {q.number} [{q.section}] [{q.q_type}] ---")
        if q.sim_instruction:
            lines.append(f"Simulation instruction: {q.sim_instruction}")
        lines.append(f"Question: {q.question}")
        if q.options:
            lines.extend(q.options)
        lines.append(f"Standard answer: {q.correct_answer}")
        if q.skipped:
            lines.append("Status: SKIPPED (not attempted)")
        else:
            lines.append(f"Student answer:  {q.user_answer}")
        if q.is_correct is not None:
            lines.append(f"Correct: {q.is_correct}")
        if q.score is not None:
            lines.append(f"Score: {q.score}")
        if q.ai_feedback:
            lines.append(f"AI feedback: {q.ai_feedback}")
        lines.append('')

    return '\n'.join(lines)
