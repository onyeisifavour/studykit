"""
answer_matcher.py

After Call 2a returns the non-simulation question list, this module:
  1. Searches all uploaded question_bank files for the exact question text.
  2. Notes the question number from that file (as originally numbered).
  3. Finds the paired answer in the corresponding answer_bank file.

Question bank format expected (flexible):
    1.  What is the pH of pure water? [Type: MCQ; Subject: Chemistry; Topic: Acids; Format: Non-Sim]
         A. gaining electrons
         B. losing electrons      ← MCQ options count as part of Q text
         C. gaining protons
         D. losing protons

Answer bank format expected:
    1.  7 (neutral pH) [Type: MCQ]

Tags in [Type: ...; Subject: ...; Topic: ...; Format: ...; Exam: ...] format are stripped before matching.
For MCQ answers, the actual option text is stored (not the letter), so shuffling options won't break matching.
"""

import re
from typing import Optional


# ── Tag stripping ─────────────────────────────────────────────────────────────

# Matches tags in square brackets: [Type: MCQ; Subject: Physics; Topic: SI Units; Format: Non-Sim; Exam: NECO]
_TAG_PATTERN = re.compile(r'\s*\[(?:Type|Subject|Topic|Format|Exam):\s*[^;\]]*(?:;\s*(?:Type|Subject|Topic|Format|Exam):\s*[^;\]]*)*\]\s*$')


def strip_tags(text: str) -> str:
    """Removes trailing [Type: ...; Subject: ...; Topic: ...; Format: ...; Exam: ...] tags from text."""
    return _TAG_PATTERN.sub('', text).strip()


# ── Parsing ───────────────────────────────────────────────────────────────────

# Matches lines like: "1.", "1)", "Q1.", "Q.1", "12."
_Q_START = re.compile(r'^(?:Q\.?\s*)?(\d+)[.)]\s+(.*)', re.IGNORECASE)


def parse_numbered_bank(text: str) -> dict[int, str]:
    """
    Parses a numbered text file (question bank or answer bank).

    Returns { question_number: full_text_block }
    Multi-line entries (e.g. MCQ options) are joined with newlines.
    Tags in [Type: ...; Subject: ...; Topic: ...; Format: ...; Exam: ...] format are stripped from the content.
    """
    entries: dict[int, list[str]] = {}
    current_num: Optional[int] = None

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()

        m = _Q_START.match(stripped)
        if m:
            current_num = int(m.group(1))
            entries[current_num] = [strip_tags(m.group(2).strip())]
        elif current_num is not None and stripped:
            # Continuation line (e.g. MCQ option, multi-sentence answer)
            entries[current_num].append(stripped)

    return {num: '\n'.join(lines).strip() for num, lines in entries.items()}


# Convenience aliases
def parse_question_bank(text: str) -> dict[int, str]:
    """Parses question bank, stripping tags from content."""
    return parse_numbered_bank(text)


def parse_bank_with_tags(text: str) -> list[dict]:
    """
    Parses a numbered bank returning each question with BOTH its clean text
    and its trailing [Type: ...; Subject: ...; Topic: ...; Format: ...; Exam: ...] tags.

    parse_numbered_bank() strips tags from the content, so it cannot be used
    to build the tag index — this variant keeps the raw first line to extract
    tags from, while still returning tag-free question text.

    Returns:
        [ {'number': int, 'question_text': str, 'tags': {..}}, ... ]
    """
    entries: dict[int, dict] = {}
    current_num: Optional[int] = None

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()

        m = _Q_START.match(stripped)
        if m:
            current_num = int(m.group(1))
            raw_text = m.group(2).strip()
            entries[current_num] = {
                'raw': raw_text,
                'clean': [strip_tags(raw_text)],
            }
        elif current_num is not None and stripped:
            entries[current_num]['clean'].append(stripped)

    result = []
    for num, e in entries.items():
        result.append({
            'number': num,
            'question_text': '\n'.join(e['clean']).strip(),
            'tags': extract_tags(e['raw']),
        })
    return result


def parse_answer_bank(text: str) -> dict[int, str]:
    """Parses answer bank, stripping tags from content."""
    return parse_numbered_bank(text)


def extract_tags(text: str) -> dict[str, str]:
    """
    Extracts tag values from [Type: ...; Subject: ...; Topic: ...; Format: ...; Exam: ...] format.
    Returns dict of tag type to value, e.g. {'Type': 'MCQ', 'Subject': 'Physics', 'Topic': 'SI Units', 'Format': 'Non-Sim', 'Exam': 'NECO'}
    """
    match = _TAG_PATTERN.search(text)
    if not match:
        return {}
    tag_str = match.group(0).strip()[1:-1]  # Remove [ and ]
    tags = {}
    for part in tag_str.split(';'):
        part = part.strip()
        if ':' in part:
            key, value = part.split(':', 1)
            tags[key.strip()] = value.strip()
    return tags


# ── Matching ──────────────────────────────────────────────────────────────────

def find_question_match(
    question_text: str,
    topic_files: list[dict],
) -> Optional[tuple[str, int, str, str]]:
    """
    Searches all topic question banks for the given question text.

    Returns (topic_name, question_number, answer_text, full_question_text)
    or None if not found.

    Matching strategy (in order):
      1. Exact match after normalisation.
      2. The searched text appears inside the stored text (stem match for MCQs).
      3. The stored text's first line equals the searched text (stem-only search).
    """
    needle = _normalise(question_text)

    for tf in topic_files:
        q_bank = parse_question_bank(tf['questions_text'])
        a_bank = parse_answer_bank(tf['answers_text'])

        for num, full_q in q_bank.items():
            haystack       = _normalise(full_q)
            first_line     = _normalise(full_q.split('\n')[0])

            matched = (
                needle == haystack
                or needle in haystack
                or needle == first_line
                or first_line in needle   # needle contains the stem
            )

            if matched:
                answer = a_bank.get(num, '')
                return (tf['topic_name'], num, answer, full_q)

    return None


def match_all_questions(
    question_list: list[str],
    topic_files: list[dict],
) -> list[dict]:
    """
    Processes the full output of Call 2a.

    Args:
        question_list: ordered list of question texts.
                       '[EMPTY]' (or empty string) marks simulation slots.
        topic_files:   list of dicts from library_scanner.load_topic_files()

    Returns list of dicts — one per question position:
        {
          'index':         int,    # 0-based position in quiz
          'question':      str,    # full question text (with MCQ options if any)
          'answer':        str,    # matched answer text ('' if not found)
          'topic':         str,    # topic name
          'q_num':         int,    # question number in source file (-1 if unknown)
          'is_empty':      bool,   # True = simulation slot
          'match_found':   bool,   # False = text not found in any bank
        }
    """
    results = []

    for i, raw in enumerate(question_list):
        text = raw.strip()
        is_empty = not text or text.upper() == '[EMPTY]'

        if is_empty:
            results.append({
                'index':       i,
                'question':    '',
                'answer':      '',
                'topic':       '',
                'q_num':       -1,
                'is_empty':    True,
                'match_found': False,
            })
            continue

        match = find_question_match(text, topic_files)
        if match:
            topic_name, q_num, answer, full_q = match
            results.append({
                'index':       i,
                'question':    full_q,   # use the canonical full text
                'answer':      answer,
                'topic':       topic_name,
                'q_num':       q_num,
                'is_empty':    False,
                'match_found': True,
            })
        else:
            # Text not found — store as-is with no answer
            results.append({
                'index':       i,
                'question':    text,
                'answer':      '',
                'topic':       'unknown',
                'q_num':       -1,
                'is_empty':    False,
                'match_found': False,
            })

    return results


# ── MCQ option parsing ────────────────────────────────────────────────────────

_OPTION_LINE = re.compile(r'^([A-Da-d])[.)]\s+(.+)')


def split_mcq(full_question: str) -> tuple[str, list[str]]:
    """
    Splits a full MCQ question text into (stem, [options]).

    Example input:
        "What is the pH of pure water?\nA. 3\nB. 7\nC. 11\nD. 14"

    Returns:
        ("What is the pH of pure water?", ["A. 3", "B. 7", "C. 11", "D. 14"])
    """
    lines = full_question.splitlines()
    stem_lines: list[str] = []
    options: list[str] = []

    for line in lines:
        m = _OPTION_LINE.match(line.strip())
        if m:
            options.append(line.strip())
        else:
            if not options:          # only add to stem before first option
                stem_lines.append(line.strip())

    stem = ' '.join(l for l in stem_lines if l)
    return stem, options


# ── Helpers ───────────────────────────────────────────────────────────────────

def _normalise(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace for fuzzy matching."""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s]', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text
