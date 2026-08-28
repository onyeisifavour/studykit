"""
session_log.py

In-memory chronological event log for the active quiz session.
Separate from quiz_logger.py (which handles structured file persistence).

Consumed by:
  - app.py          → format_for_summary() feeds the final summary API call
  - evaluation_thread.py → get_question_context() loads per-question data for tutoring
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


# ── Data class ────────────────────────────────────────────────────────────────

@dataclass
class LogEntry:
    timestamp:  str
    entry_type: str   # 'question' | 'answer' | 'feedback' | 'system'
    q_index:    int   # 0-based; -1 for system entries
    content:    str
    metadata:   dict = field(default_factory=dict)


# ── Session log ───────────────────────────────────────────────────────────────

class SessionLog:
    """
    Running log of all quiz events in the current session.
    One instance lives for the duration of a quiz; call clear() between quizzes.
    """

    def __init__(self):
        self._entries:    list[LogEntry] = []
        self._started_at: str            = datetime.now().isoformat()

    # ── Append methods ────────────────────────────────────────────────────────

    def log_question(
        self,
        q_index:  int,
        question: str,
        *,
        topic:           str = '',
        q_type:          str = '',
        section:         str = '',
        correct_answer:  str = '',
        sim_instruction: str = '',
    ) -> None:
        self._add(
            'question', q_index, question,
            topic=topic, q_type=q_type, section=section,
            correct_answer=correct_answer, sim_instruction=sim_instruction,
        )

    def log_answer(
        self,
        q_index:    int,
        answer:     str,
        *,
        is_correct: Optional[bool] = None,
    ) -> None:
        meta = {'is_correct': is_correct} if is_correct is not None else {}
        self._add('answer', q_index, answer, **meta)

    def log_feedback(
        self,
        q_index:  int,
        feedback: str,
        *,
        score: Optional[float] = None,
    ) -> None:
        meta = {'score': score} if score is not None else {}
        self._add('feedback', q_index, feedback, **meta)

    def log_system(self, message: str) -> None:
        self._add('system', -1, message)

    # ── Summary output ────────────────────────────────────────────────────────

    def format_for_summary(self) -> str:
        """
        Serialises the full log as a plain-text block for the summary API call.
        Groups entries by question index; system events appear at the top.
        """
        if not self._entries:
            return "(No session data recorded.)"

        lines = [
            "QUIZ SESSION LOG",
            f"Started: {self._started_at}",
            "",
        ]

        # System events first
        system_entries = [e for e in self._entries if e.entry_type == 'system']
        for e in system_entries:
            lines.append(f"[{e.content}]")
        if system_entries:
            lines.append("")

        # Per-question groups in index order
        by_q: dict[int, list[LogEntry]] = {}
        for e in self._entries:
            if e.q_index >= 0:
                by_q.setdefault(e.q_index, []).append(e)

        for idx in sorted(by_q):
            group   = by_q[idx]
            q_entry = next((e for e in group if e.entry_type == 'question'), None)
            meta    = q_entry.metadata if q_entry else {}

            # Header line
            parts = [f"Question {idx + 1}"]
            if meta.get('section'):  parts.append(f"Section {meta['section']}")
            if meta.get('q_type'):   parts.append(meta['q_type'])
            if meta.get('topic'):    parts.append(meta['topic'])
            lines.append("--- " + " | ".join(parts) + " ---")

            if meta.get('sim_instruction'):
                lines.append(f"Simulation setup: {meta['sim_instruction']}")

            for e in group:
                if e.entry_type == 'question':
                    lines.append(f"Q: {e.content}")
                elif e.entry_type == 'answer':
                    lines.append(f"Student: {e.content}")
                    ic = e.metadata.get('is_correct')
                    if ic is not None:
                        lines.append(f"Correct: {ic}")
                elif e.entry_type == 'feedback':
                    sc = e.metadata.get('score')
                    if sc is not None:
                        lines.append(f"Score: {sc}")
                    lines.append(f"Feedback: {e.content}")

            if meta.get('correct_answer'):
                lines.append(f"Standard answer: {meta['correct_answer']}")

            lines.append("")

        return "\n".join(lines)

    # ── Per-question context (for evaluation thread) ──────────────────────────

    def get_question_context(self, q_index: int) -> dict:
        """
        Returns all recorded data for one question as a flat dict.
        Used by evaluation_thread.py to load question context for tutoring.
        Returns {} if no data exists for that index.
        """
        group = [e for e in self._entries if e.q_index == q_index]
        if not group:
            return {}

        q_entry = next((e for e in group if e.entry_type == 'question'), None)
        a_entry = next((e for e in group if e.entry_type == 'answer'),   None)
        f_entry = next((e for e in group if e.entry_type == 'feedback'), None)
        meta    = q_entry.metadata if q_entry else {}

        return {
            'question':        q_entry.content if q_entry else '',
            'user_answer':     a_entry.content if a_entry else '',
            'ai_feedback':     f_entry.content if f_entry else '',
            'correct_answer':  meta.get('correct_answer', ''),
            'topic':           meta.get('topic', ''),
            'section':         meta.get('section', ''),
            'q_type':          meta.get('q_type', ''),
            'sim_instruction': meta.get('sim_instruction', ''),
            'score':           f_entry.metadata.get('score') if f_entry else None,
            'is_correct':      a_entry.metadata.get('is_correct') if a_entry else None,
        }

    def get_all_contexts(self) -> list[dict]:
        """
        Returns get_question_context() for every logged question index, in order.
        Used to build the review page question list.
        """
        indices = sorted({e.q_index for e in self._entries if e.q_index >= 0})
        return [self.get_question_context(i) for i in indices]

    # ── State management ──────────────────────────────────────────────────────

    def clear(self) -> None:
        """Resets the log for a new quiz session."""
        self._entries.clear()
        self._started_at = datetime.now().isoformat()

    @property
    def entries(self) -> list[LogEntry]:
        return list(self._entries)

    @property
    def question_count(self) -> int:
        """Number of distinct questions that have been logged."""
        return len({e.q_index for e in self._entries if e.q_index >= 0})

    @property
    def started_at(self) -> str:
        return self._started_at

    # ── Private ───────────────────────────────────────────────────────────────

    def _add(self, entry_type: str, q_index: int, content: str, **metadata) -> None:
        self._entries.append(LogEntry(
            timestamp=datetime.now().isoformat(),
            entry_type=entry_type,
            q_index=q_index,
            content=content,
            # Strip out empty/None values to keep metadata clean
            metadata={k: v for k, v in metadata.items() if v is not None and v != ''},
        ))
