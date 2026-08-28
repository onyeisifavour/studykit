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
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional


LOGS_DIR = Path.home() / '.quiz_app' / 'logs'


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
    user_answer:   str            = ''
    is_correct:    Optional[bool] = None   # MCQ local marking
    score:         Optional[float]= None   # Section B AI score (0–1)
    ai_feedback:   str            = ''
    topic:         str            = ''
    sim_instruction: str          = ''     # simulation pre-question instruction
    skipped:       bool           = False  # user hit Skip rather than answering


@dataclass
class QuizLog:
    quiz_id:        str
    created_at:     str
    topics:         list[str]
    evaluation_on:  bool                        = True
    skip_mode:      str                         = 'zero'   # 'zero' | 'exclude' — chosen at quiz start
    completed:      bool                        = False
    summary_report: str                         = ''
    questions:      list[QuestionRecord]        = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> 'QuizLog':
        raw_questions = d.pop('questions', [])
        obj = cls(**d)
        obj.questions = [QuestionRecord(**q) for q in raw_questions]
        return obj

    # ── Derived stats ──────────────────────────────────────────────────────────

    def mcq_score(self) -> tuple[int, int]:
        """Returns (correct_count, total_mcq), respecting skip_mode."""
        mcq = [q for q in self.questions if q.q_type == 'MCQ']
        if self.skip_mode == 'exclude':
            mcq = [q for q in mcq if not q.skipped]
        correct = sum(1 for q in mcq if q.is_correct and not q.skipped)
        return correct, len(mcq)

    def subj_score(self) -> tuple[float, int]:
        """Returns (total_score_sum, total_subj_questions_scored), respecting skip_mode."""
        subj = [q for q in self.questions if q.q_type == 'SUBJ']
        if self.skip_mode == 'exclude':
            subj = [q for q in subj if not q.skipped]
        # Under 'zero' mode a skipped question counts as a 0 even though it
        # was never actually scored by the AI — under 'exclude' it's already
        # been filtered out above, so this just catches genuinely-scored ones.
        scored = [q for q in subj if q.score is not None or q.skipped]
        total = sum((q.score or 0.0) for q in scored)
        return total, len(scored)


# ── CRUD ──────────────────────────────────────────────────────────────────────

def new_quiz_log(topics: list[str], evaluation_on: bool = True, skip_mode: str = 'zero') -> QuizLog:
    quiz_id = datetime.now().strftime('%Y%m%d_%H%M%S')
    return QuizLog(
        quiz_id=quiz_id,
        created_at=datetime.now().isoformat(),
        topics=topics,
        evaluation_on=evaluation_on,
        skip_mode=skip_mode,
    )


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
                'path':       str(path),
            })
        except Exception:
            continue
    return summaries


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
