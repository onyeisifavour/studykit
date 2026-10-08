"""
option_generator.py

Stage 1b of the simulation track: multiple-choice option authoring.

The sim-question-generator agent authors a question and its correct answer only.
This module owns the deterministic half of the follow-up stage that writes the
four options for the MCQ items among those questions:

  - building the per-item prompt (stem, answer, diagnostic context)
  - parsing / validating the agent's response
  - the mechanical item-writing rules, enforced in code

Why the rules live here and not in a second agent round
-------------------------------------------------------
The checks that matter are deterministic: option count, duplicates, unit
agreement, banned phrases, length spread. A model cannot check these more
reliably than arithmetic, and a second serial call roughly doubles the latency
of an already-serial sim stretch. So one agent call does the judgement work
(pick the error types, write the options), and this module verifies.

The rule that prompted the redesign
-----------------------------------
Observed in real generated output: the correct option was the longest option
in 5 of 5 unique MCQs, and was always option A. Correct options averaged ~480
characters against ~200 for distractors. That is a 2.4x length gap plus a
fixed position - a student could score full marks by picking the longest
option without reading any physics.

So options STATE the answer; they do not explain it. The reasoning that makes a
distractor diagnostic moves to `option_rationales`, which is stored but not
displayed. The single exception is a stem that explicitly asks which reasoning
is correct, where the reasoning IS the thing being selected.

Correctness plumbing
--------------------
Display text and grading truth are deliberately separated:

  - `options` are display strings, free to be rephrased
  - `correct_option_index` is authoritative for grading
  - `correct_answer` remains for display and legacy fallback

Without an explicit index the grader falls back to matching `correct_answer`
against option text, which only works today because `correct_answer` embeds an
"A. " prefix. Options that state bare answers break that. The index is
therefore required, not merely convenient - it is also what lets
question_generator.shuffle_mcq_options keep working.

No agent or network calls are made from this module; agent_runner owns them.
"""

from __future__ import annotations

import json
import re
from typing import Optional

VALID_CONFIDENCE = {'high', 'medium', 'low'}

NUM_OPTIONS = 4

# Options may not differ from each other in length by more than this ratio.
# Chosen to sit above ordinary phrasing variation but well below the ~2.4x gap
# that made the correct option identifiable at a glance.
LENGTH_SPREAD_LIMIT = 1.35

# Below this, a length check is meaningless (short values like "8.2 m").
LENGTH_CHECK_MIN_CHARS = 24

# Phrases that give an item away or make it unanswerable.
BANNED_PHRASES = (
    'all of the above',
    'none of the above',
    'all of these',
    'none of these',
    'both a and b',
    'neither',
    'it depends',
    'cannot be determined',
    'not enough information',
    'impossible to say',
)

# Absolute terms that make one option trivially preferable on wording alone.
ABSOLUTE_TERMS = (
    'always',
    'never',
    'all masses',
    'completely',
    'entirely',
    'impossible',
    'never happens',
)

_ENUMERATOR_RE = re.compile(r'^\s*\(?([A-Ja-j])[).:]\s*')
_DIGIT_RE = re.compile(r'\d')
# Any numeric literal, including a bare exponent like the '26' in '10^26'.
_NUM_LITERAL_RE = re.compile(r'-?\d[\d,]*(?:\.\d+)?')
# A trailing unit token: letters/symbols/slashes/exponents, anchored at the end.
_UNIT_TOKEN_RE = re.compile(r'([A-Za-zΩµμ°][A-Za-zΩµμ°0-9²³^/·]*)\s*$')


# ── Text helpers ──────────────────────────────────────────────────────────────

def normalise_option(text: str) -> str:
    """Strips a leading enumerator like 'A.', 'B) ', '(c) ' from one option."""
    return _ENUMERATOR_RE.sub('', str(text or '')).strip()


def _compare_key(text: str) -> str:
    """
    Key for 'are these the same answer?': case-, whitespace- and unit-spacing-
    insensitive, but otherwise literal.

    Near-misses are deliberately NOT collapsed: '8.2 m' and '8.3 m' must stay
    two distinct options, since that difference is often the whole point.
    """
    s = re.sub(r'\s+', '', str(text or '')).lower()
    return s.replace(' ', '')


def _strip_math(text: str) -> str:
    """Removes LaTeX delimiters/commands so shape checks see the bare value."""
    s = re.sub(r'\$\$?', '', str(text or ''))
    s = re.sub(r'\\[a-zA-Z]+', ' ', s)
    s = s.replace('{', ' ').replace('}', ' ').replace('^', ' ')
    return s


def _is_numeric(text: str) -> bool:
    return bool(_DIGIT_RE.search(_strip_math(text)))


def _kind_of(text: str) -> str:
    return 'numeric' if _is_numeric(text) else 'textual'


def unit_of(text: str) -> str:
    """
    Trailing unit token of a numeric option, or '' when it has no unit.

    Takes the whitespace-delimited tail, which is how units are actually written
    in our real output: '8.2 m' -> 'm', '12 km/s' -> 'km/s',
    '1.89 x 10^26 N' -> 'n', '10 m/s^2' -> 'm/s', '0.004 M_sun' -> 'sun'.

    A tail that is purely numeric is not a unit, which also keeps glued forms
    ('2x', '4a') from being mistaken for one.

    Only ever needs to agree across the four options, so this is intentionally
    loose: it compares token shapes, not physical units.
    """
    s = _strip_math(text).strip()
    if not _DIGIT_RE.search(s):
        return ''
    parts = s.split()
    if len(parts) < 2:
        return ''
    tail = parts[-1]
    if _DIGIT_RE.search(tail):
        # A trailing exponent rather than a unit. The unit, if any, is the
        # whitespace-delimited token before it: '10 m/s^2' -> 'm/s'.
        if len(parts) < 3:
            return ''
        tail = parts[-2]
    m = _UNIT_TOKEN_RE.search(tail)
    if not m:
        return ''
    return m.group(1).strip().lower()


def option_length(text: str) -> int:
    return len(str(text or '').strip())


# ── Mechanical item-writing checks ────────────────────────────────────────────

def audit_options(
    options: list[str],
    correct_index: Optional[int],
) -> list[str]:
    """
    Returns human-readable warnings about the four options.

    An empty list means every mechanical rule passed. These are quality
    signals, not validity checks: the caller decides how to treat them, and a
    slightly awkward distractor is far less harmful than losing the question.
    """
    warnings: list[str] = []
    opts = [normalise_option(o) for o in options]

    if len(opts) != NUM_OPTIONS:
        warnings.append(f'expected {NUM_OPTIONS} options, got {len(opts)}')

    if any(not o for o in opts):
        warnings.append('at least one option is empty')

    keys = [_compare_key(o) for o in opts]
    dupes = {k for k in keys if k and keys.count(k) > 1}
    if dupes:
        warnings.append(f'duplicate options: {sorted(dupes)}')

    if correct_index is None or not (0 <= correct_index < len(opts)):
        warnings.append(
            f'correct_index {correct_index!r} is not a valid option position')
    else:
        correct = opts[correct_index]

        # Homogeneity: one option of a different kind is identifiable without
        # reasoning, which defeats the item.
        want_kind = _kind_of(correct)
        odd = [o for o in opts if o and _kind_of(o) != want_kind]
        if odd:
            warnings.append(
                f'options of a different kind than the correct answer '
                f'({want_kind}): {odd}')

        if want_kind == 'numeric':
            want_unit = unit_of(correct)
            if want_unit:
                mismatched = sorted({
                    unit_of(o) for o in opts
                    if o and _is_numeric(o) and unit_of(o) != want_unit
                } - {''})
                if mismatched:
                    warnings.append(
                        f'numeric options using a different unit than '
                        f'{want_unit!r}: {mismatched}')

        # Giveaway phrases, checked on every option.
        for i, o in enumerate(opts):
            low = o.lower()
            for phrase in BANNED_PHRASES:
                if phrase in low:
                    warnings.append(
                        f'option {i} contains the giveaway phrase {phrase!r}')
            for term in ABSOLUTE_TERMS:
                if term in low:
                    warnings.append(
                        f'option {i} contains the absolute term {term!r}')

        # The length cue. This is the check that addresses the observed defect:
        # the correct option being consistently the longest.
        lens = [option_length(o) for o in opts]
        if max(lens) >= LENGTH_CHECK_MIN_CHARS:
            lo, hi = min(lens), max(lens)
            if lo > 0 and hi / lo > LENGTH_SPREAD_LIMIT:
                longest_is_correct = (lens[correct_index] == hi)
                warnings.append(
                    f'length spread {hi}/{lo} = {hi / lo:.2f} exceeds '
                    f'{LENGTH_SPREAD_LIMIT}'
                    + (' — and it is the CORRECT option, so length gives the '
                       'answer away' if longest_is_correct else ''))
    return warnings


# ── Prompt ────────────────────────────────────────────────────────────────────

_REASONING_STEM_MARKERS = (
    'which reasoning',
    'which explanation',
    'which account',
    'which reasoning is correct',
    'which explanation is correct',
    'which physical account',
    'which of the following reasoning',
    'which of these reasoning',
)


def _asks_for_reasoning(stem: str) -> bool:
    low = (stem or '').lower()
    return any(m in low for m in _REASONING_STEM_MARKERS)


def build_option_prompt(
    item: dict,
    diagnostic_context: str = '',
) -> str:
    """
    Formats the prompt for the sim-option-generator agent for one MCQ item.

    `item` is a parsed sim-track selected item (the shape produced by
    sim_generator.parse_sim_question_response). `diagnostic_context` is the
    serialised background reports and is advisory only - the item's
    `target_issue` is the authoritative signal for this slot.
    """
    q = item.get('selected_question', {}) or {}
    slot = item.get('slot_number')
    stem = (q.get('text') or '').strip()
    answer = (q.get('correct_answer') or '').strip()
    target_issue = item.get('target_issue') or q.get('target_issue') or ''
    reasoning_mode = _asks_for_reasoning(stem)

    if reasoning_mode:
        style_rule = (
            "This stem asks WHICH REASONING is correct, so the reasoning IS the "
            "thing being selected. Each option must therefore give a distinct "
            "account of the physics, and exactly one account may be valid.\n"
            "Still avoid the tell where one option is simply the longest: keep "
            "the accounts comparable in length and structure."
        )
    else:
        style_rule = (
            "STATE THE ANSWER. Do NOT explain or justify it inside the option. "
            "A student should be able to choose the right option purely by "
            "checking the value against the simulation, and a student who "
            "guesses on writing style must not do better than one who "
            "understood. All four options must be phrased the same way and be "
            "close in length — if the correct answer is the longest option, the "
            "item is broken and every student will learn that cue instead of "
            "the physics."
        )

    sections = [
        "You are writing the ANSWER OPTIONS for a diagnostic quiz question that "
        "has already been authored. Do NOT rewrite the stem, the simulation, or "
        "the meaning of the required answer.\n",
        "=== QUESTION (fixed - do not change) ===\n"
        f"{stem}\n",
        "=== REQUIRED CORRECT ANSWER (fixed) ===\n"
        f"{answer}\n",
        "=== WHAT THE STUDENT DOES ===\n"
        f"{(q.get('sim_instruction') or '').strip()}\n",
        "=== SLOT PROFILE ===\n"
        f"slot_number: {slot}\n"
        f"objective_type: {item.get('objective_type', '')}\n"
        f"target_issue: {target_issue}\n",
    ]

    if diagnostic_context.strip():
        sections.append(
            "=== DIAGNOSTIC CONTEXT (advisory) ===\n"
            "Use it to understand the misconceptions in play. The slot's "
            "target_issue above is the authoritative one.\n\n"
            f"{diagnostic_context.strip()}\n"
        )

    sections.append(
        "=== RULES ===\n"
        f"1. Return exactly {NUM_OPTIONS} options, indexed 0 to "
        f"{NUM_OPTIONS - 1}.\n"
        "2. Exactly one option is correct. It must state the required answer "
        "above. You may reword it lightly so all options read consistently, "
        "but it must keep the same value and the same unit — never a value a "
        "student could reasonably argue for instead.\n"
        "3. The other three must be plausible wrong answers, each the natural "
        "result of a DIFFERENT mistake. Choose the error types yourself from "
        "target_issue and the diagnostic context: a missed or misapplied step, "
        "a misread constraint, a known misconception, a wrong inverse-square "
        "or scaling relationship, or a near-miss numeric slip such as one "
        "factor of 4 or 10. Do not pad with random or wildly out-of-range "
        "values.\n"
        f"4. {style_rule}\n"
        "5. Never label options A/B/C/D in the strings; the app assigns those.\n"
        "6. Never use 'all of the above', 'none of the above', 'it depends', or "
        "similar giveaway phrasing.\n"
        "7. Every option must use the same unit as the correct answer, and be "
        "the same kind of thing (all numbers with that unit, or all short "
        "textual answers).\n"
        "8. For each of the three distractors, give a one-sentence rationale "
        "naming the specific mistake that produces it, in the form "
        "\"You likely <mistake>, which leads to this answer.\"\n"
    )

    from .prompts import MATH_NOTATION_SPEC
    sections.append(MATH_NOTATION_SPEC + "\n")

    sections.append(
        "Return ONLY a JSON object:\n"
        "{\n"
        f'  "slot_number": {slot},\n'
        f'  "options": ["<option 0>", "<option 1>", "<option 2>", '
        f'"<option 3>"],\n'
        '  "correct_index": <int 0-3>,\n'
        '  "rationales": ["<empty: the correct option>", '
        '"<distractor 1 rationale>", "<distractor 2 rationale>", '
        '"<distractor 3 rationale>"],\n'
        '  "error_types": ["<short name of each error used, correct option '
        'gets \\"correct\\">"],\n'
        '  "match_confidence": "high|medium|low"\n'
        "}\n"
    )
    return '\n'.join(sections)


# ── Response parsing ──────────────────────────────────────────────────────────

def _extract_json(text: str) -> Optional[object]:
    """Parses a JSON object from raw model output, tolerating code fences."""
    raw = (text or '').strip()
    if not raw:
        return None
    attempts = []
    m = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', raw, re.DOTALL)
    if m:
        attempts.append(m.group(1))
    attempts.append(raw)
    start, end = raw.find('{'), raw.rfind('}')
    if start != -1 and end > start:
        attempts.append(raw[start:end + 1])
    for attempt in attempts:
        try:
            return json.loads(attempt)
        except json.JSONDecodeError:
            continue
    return None


def parse_option_response(
    text: str,
    item: dict,
) -> tuple[Optional[list[str]], Optional[int], list[str], list[str], list[str]]:
    """
    Parses the sim-option-generator response for one item.

    Returns (options, correct_index, rationales, error_types, warnings):
      - options is the cleaned option list, or None if the response is
        unusable; the caller then leaves the item as free-response rather than
        failing the quiz build.
      - correct_index is resolved against the required answer text where
        possible, because that text is the source of truth and the model's
        index is not.
      - rationales is a list aligned to options, empty for the correct option.
      - error_types is a list aligned to options holding the model's own short
        label for the mistake each distractor represents. The correct option is
        always recorded as 'correct', whatever the model returned. Keeping the
        model's own wording matters: the taxonomy is the model's choice, not a
        fixed list this module imposes.
      - warnings carries mechanical quality problems for the pipeline.
    """
    parsed = _extract_json(text)
    if not isinstance(parsed, dict):
        return None, None, [], [], ['option agent did not return a JSON object']

    raw_opts = parsed.get('options')
    if not isinstance(raw_opts, list) or not raw_opts:
        return None, None, [], [], ['option agent returned no "options" array']
    if not all(isinstance(o, str) for o in raw_opts):
        return None, None, [], [], ['options must all be strings']

    opts = [normalise_option(o) for o in raw_opts]
    warnings: list[str] = []

    # Rationales, aligned to option positions.
    rationales: list[str] = []
    raw_rats = parsed.get('rationales')
    if isinstance(raw_rats, list):
        for i in range(len(opts)):
            val = raw_rats[i] if i < len(raw_rats) else ''
            rationales.append(str(val).strip() if isinstance(val, str) else '')
    else:
        rationales = [''] * len(opts)

    # Error types, aligned to option positions. The model picks the label for
    # each distractor itself, so this is stored verbatim rather than mapped onto
    # a closed vocabulary.
    raw_types = parsed.get('error_types')
    error_types: list[str] = []
    if isinstance(raw_types, list):
        for i in range(len(opts)):
            val = raw_types[i] if i < len(raw_types) else ''
            error_types.append(str(val).strip() if isinstance(val, str) else '')
    else:
        error_types = [''] * len(opts)
        warnings.append('option agent returned no "error_types" array')

    # Resolve the correct option. Prefer the required answer text, because a
    # reworded correct option will not match text exactly and the model's own
    # index is the only remaining signal.
    required = normalise_option(
        (item.get('selected_question', {}) or {}).get('correct_answer', ''))
    declared = parsed.get('correct_index')
    chosen: Optional[int] = None
    if isinstance(declared, int) and not isinstance(declared, bool) \
            and 0 <= declared < len(opts):
        chosen = declared

    exact = [i for i, o in enumerate(opts)
             if required and _compare_key(o) == _compare_key(required)]

    if chosen is None:
        if len(exact) == 1:
            chosen = exact[0]
        else:
            warnings.append(
                'option agent gave no usable correct_index and the required '
                f'answer {required!r} did not match exactly; trusting the '
                "agent's own correct_index where possible")
    elif exact and chosen not in exact:
        warnings.append(
            f'option agent marked index {chosen} correct, but the required '
            f'answer {required!r} sits at index {exact[0]}; using the required '
            'answer instead')
        chosen = exact[0]

    if required and not exact:
        warnings.append(
            f'no option exactly states the required answer {required!r}; '
            'the correct option is a rewording of it')

    # Rationales are required for distractors and forbidden for the correct one:
    # a rationale on the correct option is an explanation, which is precisely
    # what we removed from the options themselves.
    if chosen is not None and 0 <= chosen < len(rationales):
        if rationales[chosen]:
            warnings.append(
                'the correct option carries a rationale; it should explain why '
                'the DISTRACTORS are wrong, not the correct answer')
            rationales[chosen] = ''
    missing = [i for i, r in enumerate(rationales)
               if i != chosen and not r]
    if missing:
        warnings.append(
            f'distractors {missing} have no rationale naming their mistake')

    # The correct option is not an error, whatever the model labelled it.
    if chosen is not None and 0 <= chosen < len(error_types):
        if error_types[chosen] and error_types[chosen].lower() != 'correct':
            warnings.append(
                f'the correct option was labelled error type '
                f'{error_types[chosen]!r}; recording it as "correct"')
        error_types[chosen] = 'correct'

    warnings.extend(audit_options(opts, chosen))
    return opts, chosen, rationales, error_types, warnings