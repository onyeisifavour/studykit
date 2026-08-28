"""
flashcard_builder.py

Builds flashcard decks from two sources, both derived on demand from
existing data — nothing new is stored:

1. Quiz-log missed questions ("From your quizzes"):
   Questions answered incorrectly or scored under 0.5 in past quizzes.
   front = question text; back = correct answer + your answer + AI feedback.

2. Learning-library topic decks ("From your library"):
   Q&A pairs parsed from each topic's question_bank.txt / answer_bank.txt.
   front = question; back = matched answer (MCQ letters resolved to the
   option text so the card is self-contained).

Card / deck dataclasses are plain Python — the UI layer decides rendering.
"""

import re

from dataclasses import dataclass, field

from . import quiz_logger
from . import answer_matcher

@dataclass
class Flashcard:
    front:   str
    back:    str
    topic:   str   = ''
    subject: str   = ''
    q_type:  str   = ''
    source:  str   = ''                 # 'quiz' | 'library'
    meta:    dict  = field(default_factory=dict)


@dataclass
class Deck:
    title:   str
    source:  str                        # 'quiz' | 'library'
    subject: str = ''
    cards:   list = field(default_factory=list)

    @property
    def size(self) -> int:
        return len(self.cards)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _subject_of_topic(topic: str) -> str:
    """Best-effort subject guess from a topic label ('Physics: Newton's Laws')."""
    t = (topic or '').strip()
    if not t:
        return ''
    if ':' in t:
        return t.split(':', 1)[0].strip()
    return t.split()[0].strip() if t else ''


_OPTION_PREFIX = re.compile(r'^([A-Da-d])[.)]\s*')

# A question starts only when the number sits at column 0. Interior numbered
# lines ("1.", "2." inside a Theory question's body) and scientific-notation
# values ("4.5 × 10⁻³ km") are indented continuation lines — treating them as
# new questions would overwrite real bank entries (seen in chem L1.1).
_Q_START_UNINDENTED = re.compile(r'^(\d+)[.)]\s+(.*)')


def _parse_bank_questions(text: str) -> list[dict]:
    """
    Tolerant question-bank parse for flashcards. Unlike the pipeline parser,
    this:
      - requires the numbered line to be UNINDENTED (interior numbered lines
        stay part of the surrounding question);
      - preserves duplicate numbers instead of overwriting, so no card is
        silently dropped.

    Returns [{'number', 'question_text', 'tags'}, ...] in file order.
    """
    entries: list[dict] = []
    current: dict | None = None

    for raw_line in text.splitlines():
        m = _Q_START_UNINDENTED.match(raw_line)
        if m:
            raw_first = m.group(2).strip()
            current = {
                'number': int(m.group(1)),
                'raw': raw_first,
                'clean': [answer_matcher.strip_tags(raw_first)],
            }
            entries.append(current)
        elif current is not None and raw_line.strip():
            current['clean'].append(raw_line.strip())

    return [{
        'number':        e['number'],
        'question_text': '\n'.join(e['clean']).strip(),
        'tags':          answer_matcher.extract_tags(e['raw']),
    } for e in entries]


def _resolve_mcq_letter(front: str, answer: str) -> str:
    """
    If the stored answer is a bare option letter (e.g. 'B'), replace it with
    the matching option text from the question so the card stands alone.
    """
    letter = (answer or '').strip().upper()
    if not re.match(r'^[A-D]$', letter):
        return answer
    _stem, options = answer_matcher.split_mcq(front)
    for opt in options:
        m = _OPTION_PREFIX.match(opt.strip())
        if m and m.group(1).upper() == letter:
            rest = opt.split('.', 1)[1].strip() if '.' in opt else opt
            return f"{letter}. {rest}"
    return answer


# ── Deck builders ─────────────────────────────────────────────────────────────

def build_missed_decks(limit: int = 200) -> list[Deck]:
    """
    One deck per topic from questions missed in past quizzes.
    Missed = MCQ answered incorrectly, or written (SUBJ/Hybrid) scored < 0.5.
    Skipped questions are excluded — no answer was attempted, so there is no
    learning signal to review.
    """
    by_topic: dict[str, list[Flashcard]] = {}

    for summary in quiz_logger.list_quiz_logs()[:limit]:
        log = quiz_logger.load_quiz_log(summary['quiz_id'])
        if not log:
            continue
        for q in log.questions:
            missed = (
                (q.q_type == 'MCQ' and q.is_correct is False)
                or (q.q_type != 'MCQ' and q.score is not None and q.score < 0.5)
            )
            if not missed:
                continue
            topic = q.topic or 'Unknown topic'
            back_parts = [f"Correct answer: {q.correct_answer}"]
            if q.user_answer and q.user_answer != '(skipped)':
                back_parts.append(f"Your answer: {q.user_answer}")
            if q.ai_feedback:
                back_parts.append(f"Feedback: {q.ai_feedback}")
            by_topic.setdefault(topic, []).append(Flashcard(
                front=q.question,
                back='\n\n'.join(back_parts),
                topic=topic,
                subject=_subject_of_topic(topic),
                q_type=q.q_type,
                source='quiz',
                meta={'quiz_id': log.quiz_id, 'number': q.number},
            ))

    return [
        Deck(title=t, source='quiz', subject=_subject_of_topic(t), cards=cards)
        for t, cards in sorted(by_topic.items())
    ]


def build_topic_decks(topic_files: list[dict]) -> list[Deck]:
    """
    One deck per library topic from question_bank.txt + answer_bank.txt.
    Questions without a matched answer are skipped.
    """
    decks: list[Deck] = []
    for tf in topic_files:
        q_text = tf.get('questions_text', '')
        a_text = tf.get('answers_text', '')
        if not q_text or not a_text:
            continue

        q_bank = _parse_bank_questions(q_text)
        a_bank = answer_matcher.parse_answer_bank(a_text)

        cards = []
        for entry in q_bank:
            raw_answer = a_bank.get(entry['number'], '')
            if not raw_answer:
                continue
            cards.append(Flashcard(
                front=entry['question_text'],
                back=_resolve_mcq_letter(entry['question_text'], raw_answer),
                topic=tf.get('topic_name', ''),
                subject=tf.get('subject_name', ''),
                q_type=entry['tags'].get('Type', ''),
                source='library',
            ))

        if cards:
            decks.append(Deck(
                title=tf.get('topic_name', 'Topic'),
                source='library',
                subject=tf.get('subject_name', ''),
                cards=cards,
            ))
    return decks


def build_all_decks(topic_files: list[dict], limit: int = 200) -> list[Deck]:
    """Missed-question decks first, then library topic decks."""
    return build_missed_decks(limit=limit) + build_topic_decks(topic_files)
