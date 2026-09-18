"""
question_generator.py

Parses AI responses from:
  Call 2a — non-simulation question list (with [EMPTY] for sim slots)
  Call 2b — simulation question sets in {Set N}[...] blocks

A simulation question can be MCQ or SUBJ (type and simulation-status are
independent — see blueprint_generator.py). Each question inside a
{questions}[...] block is tagged "Q1: [MCQ] ..." or "Q1: [SUBJ] ...".
MCQ sim questions carry generated options (A–D) directly below the stem,
same as non-sim MCQs.

Then assembles the final ordered GeneratedQuestion list.

Parse-only — no API calls are made here.
API calls are orchestrated by app.py via api_client.py.

BlueprintEntry is defined here so blueprint_generator.py can import it.
"""

import hashlib
import random
import re
from dataclasses import dataclass, field
from typing import Optional

from .answer_matcher import split_mcq


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class BlueprintEntry:
    """
    One line of the quiz blueprint.
    Defined here; blueprint_generator.py imports from this module.
    """
    number:        int    # 1-based question number
    q_code:        str    # 'Q01', 'Q02', …
    q_type:        str    # 'MCQ' | 'SUBJ' | 'SIM'
    section:       str    # 'A' | 'B'
    topic:         str    # topic label from the blueprint line
    is_simulation: bool
    sim_name:      str = ''  # simulation folder name (when is_simulation)
    sim_set:       int = 0   # set grouping number (when is_simulation)


@dataclass
class SimSet:
    """
    One parsed {Set N}[...] block from the Call 2b response.
    instruction: shown to the user before the simulation questions in this set.
    questions: list of dicts, paired by position index with `answers`:
        {'q_type': 'MCQ'|'SUBJ', 'text': str, 'options': list[str]}
        (options is empty for SUBJ)
    answers: list of str, paired by position index with `questions`.
    """
    set_number:  int
    instruction: str
    questions:   list[dict] = field(default_factory=list)
    answers:     list[str]  = field(default_factory=list)


@dataclass
class GeneratedQuestion:
    """
    Fully assembled question object used throughout the quiz runtime.
    Created by build_question_list(); consumed by the quiz UI and quiz_logger.
    """
    index:           int            # 0-based position in quiz
    number:          int            # 1-based display number
    q_type:          str            # 'MCQ' | 'SUBJ' | 'SIM'
    section:         str            # 'A' | 'B'
    topic:           str
    question_text:   str            # stem only (MCQ options stored separately)
    correct_answer:  str
    options:         list[str]      = field(default_factory=list)  # MCQ options
    is_simulation:   bool           = False
    sim_name:        str            = ''
    sim_instruction: str            = ''   # instruction shown before sim question group
    match_found:     bool           = True # False if answer_matcher had no result

    # Agent 4 / 5 metadata carried from the sequence manifest to the quiz note.
    # quiz_type is the canonical manifest type — 'MCQ' | 'Hybrid' | 'Theory' —
    # kept separately from q_type so legacy consumers ('SUBJ') are unaffected.
    quiz_type:        str = ''
    subject:          str = ''
    objective_type:   str = ''
    pacing_stage:     str = ''
    position_rationale: str = ''
    source:           str = ''


# ── Patterns ──────────────────────────────────────────────────────────────────

_Q_CODE_LINE = re.compile(r'^(Q\d+):\s*(.*)', re.IGNORECASE)
_SET_HEADER  = re.compile(r'\{Set\s*(\d+)\}\s*\[', re.IGNORECASE)
_INNER_TAG   = re.compile(r'\{(instruction|questions|answers)\}\s*\[', re.IGNORECASE)
# Sim question item start: "Q1: [MCQ] stem text" or "Q1: [SUBJ] stem text"
# The [MCQ]/[SUBJ] tag is optional in the match (defaults to SUBJ) so a
# slightly malformed AI reply still parses instead of dropping the question.
_SIM_Q_START = re.compile(r'^Q(\d+):\s*(?:\[(MCQ|SUBJ)\]\s*)?(.*)', re.IGNORECASE)
_A_ITEM      = re.compile(r'^A\d+:\s*(.+)', re.IGNORECASE)


# ── Call 2a — Non-simulation question parsing ─────────────────────────────────

def parse_non_sim_questions(raw: str) -> list[tuple[str, str]]:
    """
    Parses the Call 2a AI response.

    Returns an ordered list of (q_code, question_text) tuples.
    question_text is '[EMPTY]' for simulation slot placeholders.

    Multi-line questions (MCQ options spread over several lines) are
    collected into a single newline-joined string.

    Expected response format:
        QUESTIONS_START
        Q01: What is the pH of pure water?
        Q02: [EMPTY]
        Q03: Define oxidation.
             A. gaining electrons
             B. losing electrons
             C. gaining protons
             D. losing protons
        QUESTIONS_END
    """
    if not raw or not isinstance(raw, str):
        return []

    content = _extract_between_markers(raw, 'QUESTIONS_START', 'QUESTIONS_END')

    results:    list[tuple[str, str]] = []
    curr_code:  Optional[str]         = None
    curr_lines: list[str]             = []

    for raw_line in content.splitlines():
        stripped = raw_line.strip()
        m = _Q_CODE_LINE.match(stripped)
        if m:
            # Flush previous entry
            if curr_code is not None:
                results.append((curr_code, '\n'.join(curr_lines).strip()))
            curr_code  = m.group(1).upper()
            curr_lines = [m.group(2).strip()]
        elif curr_code is not None and stripped:
            # Continuation line (e.g. MCQ option below the stem)
            curr_lines.append(stripped)

    # Flush final entry
    if curr_code is not None:
        results.append((curr_code, '\n'.join(curr_lines).strip()))

    return results


# ── Call 2b — Simulation set parsing ─────────────────────────────────────────

def parse_sim_sets(raw: str) -> list[SimSet]:
    """
    Parses the Call 2b AI response into a list of SimSet objects.

    Expected response format (one or more sets):

        {Set 1}[
        {instruction}[Set launch angle to 45°, velocity to 20 m/s. Run and record.]
        {questions}[
        Q1: What is the maximum height?
        Q2: What is the horizontal range?
        ]
        {answers}[
        A1: 10.2 metres
        A2: 40.8 metres
        ]]

    Uses bracket-counting so nested content (e.g. [brackets in text]) is
    handled correctly without false-positive splitting.
    """
    if not raw or not isinstance(raw, str):
        return []

    sets: list[SimSet] = []

    for m in _SET_HEADER.finditer(raw):
        set_num = int(m.group(1))

        # Extract the full body of this {Set N}[...] block
        block_content, _ = _extract_block_content(raw, m.end())

        instruction: str        = ''
        questions:   list[dict] = []
        answers:     list[str]  = []

        # Parse inner {instruction}[...], {questions}[...], {answers}[...] blocks
        for inner_m in _INNER_TAG.finditer(block_content):
            tag     = inner_m.group(1).lower()
            content, _ = _extract_block_content(block_content, inner_m.end())

            if tag == 'instruction':
                instruction = content.strip()

            elif tag == 'questions':
                questions = _parse_sim_questions(content)

            elif tag == 'answers':
                for line in content.splitlines():
                    am = _A_ITEM.match(line.strip())
                    if am:
                        answers.append(am.group(1).strip())

        sets.append(SimSet(
            set_number=set_num,
            instruction=instruction,
            questions=questions,
            answers=answers,
        ))

    return sets


def _parse_sim_questions(content: str) -> list[dict]:
    """
    Parses the {questions}[...] body of one sim set into a list of dicts:
        {'q_type': 'MCQ'|'SUBJ', 'text': str, 'options': list[str]}

    Handles multi-line entries so MCQ option lines (A./B./C./D.) directly
    below a "Q1: [MCQ] ..." line are captured and split out via split_mcq.
    """
    items:      list[dict]           = []
    current:    Optional[dict]       = None

    for raw_line in content.splitlines():
        stripped = raw_line.strip()
        m = _SIM_Q_START.match(stripped)
        if m:
            if current is not None:
                items.append(_finalise_sim_question(current))
            current = {
                'q_type': (m.group(2) or 'SUBJ').upper(),
                'lines':  [m.group(3).strip()] if m.group(3) else [],
            }
        elif current is not None and stripped:
            current['lines'].append(stripped)

    if current is not None:
        items.append(_finalise_sim_question(current))

    return items


def _finalise_sim_question(item: dict) -> dict:
    full_text = '\n'.join(item['lines']).strip()
    if item['q_type'] == 'MCQ':
        stem, options = split_mcq(full_text)
        return {'q_type': 'MCQ', 'text': stem, 'options': options}
    return {'q_type': 'SUBJ', 'text': full_text, 'options': []}


# ── Slot filling ──────────────────────────────────────────────────────────────

def fill_sim_slots(
    questions: list[GeneratedQuestion],
    sim_sets:  list[SimSet],
) -> list[GeneratedQuestion]:
    """
    Fills simulation slot placeholders with content from sim sets.

    Slots are identified as GeneratedQuestion items where is_simulation=True.
    Sets are consumed in order; each set fills the next N empty slots
    (N = number of questions in that set).

    - If a set has MORE questions than remaining slots: extras are discarded.
    - If a set has FEWER questions than remaining slots: those slots stay empty
      (they will be skipped during the quiz).

    Mutates the list in place and also returns it.
    """
    empty_indices = [i for i, q in enumerate(questions) if q.is_simulation]
    slot_ptr = 0

    for sim_set in sim_sets:
        n_answers = len(sim_set.answers)

        for q_idx, q_item in enumerate(sim_set.questions):
            if slot_ptr >= len(empty_indices):
                break  # All slots consumed

            target = empty_indices[slot_ptr]
            questions[target].question_text   = q_item['text']
            questions[target].options         = q_item.get('options', [])
            questions[target].correct_answer  = (
                sim_set.answers[q_idx] if q_idx < n_answers else ''
            )
            questions[target].sim_instruction = sim_set.instruction
            slot_ptr += 1

    return questions


# ── Final assembly ────────────────────────────────────────────────────────────

def build_question_list(
    blueprint_entries: list[BlueprintEntry],
    answer_matches:    list[dict],
    sim_sets:          list[SimSet],
) -> list[GeneratedQuestion]:
    """
    Assembles the final ordered question list from all sources.

    Args:
        blueprint_entries: from blueprint_generator.parse_blueprint()
        answer_matches:    from answer_matcher.match_all_questions()
                           — index values align with blueprint_entries (0-based)
        sim_sets:          from parse_sim_sets() (Call 2b)

    Returns:
        Ordered list of GeneratedQuestion, one per blueprint entry.
        Simulation slots without a matched question have question_text == ''.
        Those will be skipped during the quiz.
    """
    # 1 — Skeleton from blueprint
    questions: list[GeneratedQuestion] = []
    for entry in blueprint_entries:
        questions.append(GeneratedQuestion(
            index=entry.number - 1,
            number=entry.number,
            q_type=entry.q_type,
            section=entry.section,
            topic=entry.topic,
            is_simulation=entry.is_simulation,
            sim_name=entry.sim_name,
            question_text='',
            correct_answer='',
        ))

    # 2 — Fill non-sim slots from answer_matches
    for match in answer_matches:
        idx = match['index']
        if match['is_empty'] or idx >= len(questions):
            continue
        q = questions[idx]
        if q.is_simulation:
            continue

        full_text        = match.get('question', '')
        q.correct_answer = match.get('answer', '')
        q.match_found    = match.get('match_found', True)

        # Split MCQ stem from options for cleaner display
        if q.q_type == 'MCQ':
            stem, opts      = split_mcq(full_text)
            q.question_text = stem
            q.options       = opts
        else:
            q.question_text = full_text

        # Prefer the bank-matched topic over the blueprint's generic label
        matched_topic = match.get('topic', '')
        if matched_topic and matched_topic not in ('unknown', ''):
            q.topic = matched_topic

    # 3 — Fill simulation slots from sim sets
    fill_sim_slots(questions, sim_sets)

    return questions


# ── Agent 4 sequence → question list ──────────────────────────────────────────

def build_questions_from_sequence(
    sequence_manifest: dict,
) -> list[GeneratedQuestion]:
    """
    Converts the Agent 4 sequenced-quiz manifest into quiz-ready questions.

    Order comes straight from the manifest's ordered_quiz_sequence — nothing
    is shuffled or re-sorted here (shuffle prefs, if any, apply afterward via
    shuffle_questions()). The manifest never contains empty placeholder
    questions, so every entry yields a usable question.

    Args:
        sequence_manifest: Agent 4 output with an ordered_quiz_sequence array;
                           each entry has sequence_index, question
                           (text/type/subject/topic/format/options/
                           correct_answer), objective_type, source,
                           pacing_stage, position_rationale.

    Returns:
        Ordered list of GeneratedQuestion whose index/number match the
        manifest sequence positions (0- and 1-based respectively).
    """
    questions: list[GeneratedQuestion] = []
    for i, entry in enumerate(sequence_manifest.get('ordered_quiz_sequence', [])):
        q = entry.get('question', {})
        q_type = q.get('type', 'Hybrid')
        is_sim = q.get('format', 'Non-Sim') == 'Sim'
        questions.append(GeneratedQuestion(
            index=i,
            number=i + 1,
            q_type='MCQ' if q_type == 'MCQ' else 'SUBJ',
            section='A' if q_type == 'MCQ' else 'B',
            topic=q.get('topic', ''),
            question_text=q.get('text', ''),
            correct_answer=q.get('correct_answer', ''),
            options=q.get('options') or [],
            is_simulation=is_sim,
            sim_name=q.get('sim_name', ''),
            sim_instruction=q.get('sim_instruction', ''),
            match_found=True,
            quiz_type=q_type,
            subject=q.get('subject', ''),
            objective_type=entry.get('objective_type', ''),
            pacing_stage=entry.get('pacing_stage', ''),
            position_rationale=entry.get('position_rationale', ''),
            source=entry.get('source', ''),
        ))
    shuffle_mcq_options(questions)
    return questions


# ── MCQ option shuffling ──────────────────────────────────────────────────────

_OPTION_LETTERS = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J']


def _relabel_option(text: str, letter: str) -> str:
    """Rewrites a leading 'A.' label on an option to the given letter."""
    text = (text or '').strip()
    label = re.match(r'^[A-Za-z]\s*\.\s*', text)
    if label:
        return text[:label.start()] + f'{letter}. ' + text[label.end():]
    return f'{letter}. {text}'


def _option_correct_index(options: list[str], correct_answer: str) -> Optional[int]:
    """Locates the correct option by exact text match, then leading-letter."""
    ca = (correct_answer or '').strip()
    for i, o in enumerate(options):
        if (o or '').strip() == ca:
            return i
    head = ca[:1].upper() if ca and ca[:1].isalpha() else ''
    if head:
        for i, o in enumerate(options):
            if (o or '').strip().upper().startswith(head):
                return i
    return None


def shuffle_mcq_options(questions: list) -> list:
    """
    Reorders each MCQ question's answer options so the correct answer is not
    always 'A', relabeling option letters and correct_answer consistently.

    The permutation is derived deterministically from the option texts, so a
    quiz rebuilt from the same manifest (e.g. a resume) reproduces the very
    same option order and the persisted note stays reusable via its content
    signature.
    """
    for q in questions:
        if str(getattr(q, 'q_type', '')) != 'MCQ':
            continue
        opts = list(getattr(q, 'options', []) or [])
        if len(opts) < 2:
            continue
        correct = _option_correct_index(opts, getattr(q, 'correct_answer', ''))
        if correct is None:
            continue
        joined = '\x1f'.join((o or '').strip() for o in opts)
        order = list(range(len(opts)))
        random.Random(hashlib.sha256(joined.encode('utf-8')).hexdigest()).shuffle(order)
        q.options = [_relabel_option(opts[i], _OPTION_LETTERS[k])
                     for k, i in enumerate(order)]
        new_pos = order.index(correct)
        q.correct_answer = _relabel_option(opts[correct], _OPTION_LETTERS[new_pos])
    return questions


# ── Shuffling ─────────────────────────────────────────────────────────────────

def shuffle_questions(
    questions: list[GeneratedQuestion],
    keep_sim_together: bool,
) -> list[GeneratedQuestion]:
    """
    Reorders the final question list according to the shuffle preference.

    Args:
        questions: final ordered list from build_question_list().
        keep_sim_together: True groups questions from the same simulation into
            atomic blocks (original relative order preserved within each block)
            and shuffles those blocks together with individual non-sim
            questions. False shuffles every question freely — each question
            retains its sim_instruction, so sim questions stay self-contained.

    Returns:
        A new list with `index` and `number` renumbered to the new positions.
        When keep_sim_together is True, shuffling is skipped entirely if there
        are no simulation questions.
    """
    if not questions:
        return questions

    if keep_sim_together:
        blocks:    list[list[GeneratedQuestion]] = []
        sim_groups: dict[str, list[GeneratedQuestion]] = {}
        sim_order: list[str] = []

        for q in questions:
            if q.is_simulation and q.sim_name:
                if q.sim_name not in sim_groups:
                    sim_groups[q.sim_name] = []
                    sim_order.append(q.sim_name)
                sim_groups[q.sim_name].append(q)
            else:
                blocks.append([q])

        for name in sim_order:
            blocks.append(sim_groups[name])

        random.shuffle(blocks)
        shuffled = [q for block in blocks for q in block]
    else:
        shuffled = list(questions)
        random.shuffle(shuffled)

    for i, q in enumerate(shuffled):
        q.index  = i
        q.number = i + 1

    return shuffled


# ── Private helpers ───────────────────────────────────────────────────────────

def _extract_between_markers(text: str, start: str, end: str) -> str:
    """
    Returns the substring between `start` and `end` markers (exclusive).
    Falls back to the full text if either marker is absent.
    """
    s = text.find(start)
    e = text.find(end)
    if s != -1 and e != -1:
        return text[s + len(start): e]
    return text


def _extract_block_content(text: str, offset: int) -> tuple[str, int]:
    """
    Starting at `offset` (the character position *after* an opening '['),
    reads forward using bracket-counting until the matching ']' is found.

    Returns (content_string, position_after_closing_bracket).
    Handles nested brackets correctly.
    """
    depth = 1
    i     = offset
    while i < len(text) and depth > 0:
        ch = text[i]
        if   ch == '[': depth += 1
        elif ch == ']': depth -= 1
        i += 1
    return text[offset: i - 1], i
