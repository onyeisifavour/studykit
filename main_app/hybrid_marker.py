"""
hybrid_marker.py

Strict right/wrong marking for Hybrid questions (typed final answers such as
numbers, expressions, or short precise statements).

Strategy (per approved plan):
  1. Deterministic fast path — normalise both the student answer and the
     standard answer (casing, whitespace, trailing punctuation, common math
     spellings) and accept an exact match immediately.
  2. AI fallback — when the strings differ, ask the model to mark strictly
     against the standard answer with explicit notation / casing / final-
     answer-format rules (HYBRID_EVAL_SYSTEM), and parse the RIGHT/WRONG
     verdict. This keeps mathematically-correct but differently-formatted
     answers from being marked wrong by a naïve string comparison.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Optional

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


def hybrid_is_correct_strict(user_answer: str, correct_answer: str) -> bool:
    """Deterministic fast-path check. Conservative: only exact-normalised
    equality counts as right here."""
    left  = normalize_hybrid(user_answer)
    right = normalize_hybrid(correct_answer)
    return bool(left) and left == right


# ── AI verdict parsing ───────────────────────────────────────────────────────

_RESULT_HEAD = re.compile(r'RESULT\s*:\s*(RIGHT|WRONG|CORRECT|INCORRECT)',
                          re.IGNORECASE)
_EXPLANATION = re.compile(r'EXPLANATION\s*:\s*(.+?)(?=\n\s*RESULT|$)',
                          re.IGNORECASE | re.DOTALL)


def parse_hybrid_verdict(response: str) -> tuple[Optional[bool], str]:
    """Parses an AI hybrid verdict into (is_correct, explanation).

    Returns (None, raw) when no verdict line is found so callers can fall
    back to conservative 'wrong' rather than crashing on a malformed reply.
    """
    if not response or not isinstance(response, str):
        return None, ''
    m = _RESULT_HEAD.search(response)
    if not m:
        return None, response.strip()
    verdict = m.group(1).upper()
    is_correct = verdict in ('RIGHT', 'CORRECT')
    exp = _EXPLANATION.search(response)
    explanation = exp.group(1).strip() if exp else response.strip()
    return is_correct, explanation