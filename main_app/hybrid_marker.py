"""
hybrid_marker.py

Deterministic fast path for Hybrid questions (typed final answers such as
numbers, expressions, or short precise statements).

Strategy: normalise both the student answer and the standard answer (casing,
whitespace, trailing punctuation, common math spellings) and accept an exact
match immediately — this settles most Hybrid answers without spending an API
call, since they ride the shared subjective batch alongside Theory.

Anything the matcher cannot settle falls through to the batched evaluator, which
grades it against the standard and snaps the raw score to strict binary credit
(quiz_note.snap_hybrid_score).
"""

from __future__ import annotations

import re
import unicodedata

# Common '×'/'·'/'*' separators and unicode dashes ('−' minus) normalise to a
# single canonical token so the fast path is useful without being brittle.
_UNI_MAP = {
    '\u00d7': 'x',   # ×
    '\u00b7': '.',   # ·
    '\u2022': '.',   # •
    '\u2212': '-',   # −
    '\u2013': '-',   # –
    '\u2014': '-',   # —
    '\uff0d': '-',   # －
}


def normalize_hybrid(text: str) -> str:
    """
    Lenient normalisation used only by the deterministic fast path:
      - strip, casefold, collapse whitespace
      - unify common multiplication/separator/minus glyphs
      - drop a single trailing period (sentence punctuation)
    Deliberately NOT smart enough to approve wrong answers — anything that
    still differs after this falls through to the AI grader.
    """
    if text is None:
        return ''
    s = str(text)
    s = unicodedata.normalize('NFKC', s)
    for src, dst in _UNI_MAP.items():
        s = s.replace(src, dst)
    s = re.sub(r'\s+', '', s.strip())
    s = re.sub(r'\.$', '', s)
    return s.casefold()


def hybrid_exact_match(user_answer: str, correct_answer: str) -> bool:
    """
    Deterministic fast path: True only when the answers match after lenient
    normalisation.

    This can only ever shortcut a question to RIGHT. A False means "ask the
    evaluator", never "wrong" — so a correct answer that merely phrased or
    noted the standard differently still reaches the batched evaluator, which
    treats equivalent forms as correct. That is what keeps leniency and binary
    credit compatible: binary decides *how much*, the evaluator decides *whether*.
    """
    left  = normalize_hybrid(user_answer)
    right = normalize_hybrid(correct_answer)
    return bool(left) and left == right


# Retained alias for the previous name, which read as "judge this strictly"
# when it actually means "exact match only, otherwise defer to the evaluator".
hybrid_is_correct_strict = hybrid_exact_match
