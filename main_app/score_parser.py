"""
score_parser.py

Parses AI evaluation responses to extract numeric scores and explanations.

Supported formats:

── Single question ──────────────────────────────────────────────────────────
  SCORE: 0.75
  EXPLANATION: Your answer covered the main idea but missed the example.

── Multiple sub-questions ───────────────────────────────────────────────────
  QUESTION 1A:
  SCORE: 1.0
  EXPLANATION: Correct definition.

  QUESTION 1B:
  SCORE: 0.5
  EXPLANATION: Missing the example.
"""

import re
from dataclasses import dataclass


# ── Data class ────────────────────────────────────────────────────────────────

@dataclass
class ScoreResult:
    label:       str    # sub-question label ('1A', '1B') or '' for single questions
    score:       float  # 0.0 – 1.0
    explanation: str    # full explanation text


# ── Regex patterns ────────────────────────────────────────────────────────────

_SCORE_LINE     = re.compile(r'SCORE\s*:\s*([0-9]*\.?[0-9]+)', re.IGNORECASE)
_SECTION_HEAD   = re.compile(r'^QUESTION\s+([\w\d]+)\s*:', re.IGNORECASE | re.MULTILINE)
_EXPLANATION    = re.compile(
    r'EXPLANATION\s*:\s*(.+?)(?=\n\s*(?:QUESTION|SCORE)|$)',
    re.IGNORECASE | re.DOTALL,
)


# ── Public API ────────────────────────────────────────────────────────────────

def parse_single_score(response: str) -> ScoreResult:
    """
    Parses a response containing one SCORE / EXPLANATION pair.
    """
    score       = _extract_score(response)
    explanation = _extract_explanation(response)
    return ScoreResult(label='', score=score, explanation=explanation)


def parse_multi_scores(response: str) -> list[ScoreResult]:
    """
    Parses a response with multiple QUESTION X: / SCORE: / EXPLANATION: blocks.
    Falls back to parse_single_score if no section headers are found.
    """
    headers = list(_SECTION_HEAD.finditer(response))

    if not headers:
        return [parse_single_score(response)]

    results: list[ScoreResult] = []
    for i, header in enumerate(headers):
        label   = header.group(1).strip()
        start   = header.end()
        end     = headers[i + 1].start() if i + 1 < len(headers) else len(response)
        segment = response[start:end]

        score       = _extract_score(segment)
        explanation = _extract_explanation(segment)
        results.append(ScoreResult(label=label, score=score, explanation=explanation))

    return results


def strip_score_from_reply(response: str) -> str:
    """
    Removes the SCORE: line from an AI evaluation reply so only the
    human-readable explanation is shown to the user during live quiz play.
    """
    cleaned = _SCORE_LINE.sub('', response)
    # Also remove bare "SCORE:" with no value
    cleaned = re.sub(r'SCORE\s*:\s*\n', '', cleaned, flags=re.IGNORECASE)
    # Collapse excessive blank lines left behind
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    return cleaned.strip()


def scores_to_percentage(results: list[ScoreResult]) -> float:
    """
    Converts a list of ScoreResults to an overall percentage (0–100).
    Each result is weighted equally.
    """
    if not results:
        return 0.0
    total = sum(r.score for r in results)
    return round((total / len(results)) * 100, 1)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_score(text: str) -> float:
    m = _SCORE_LINE.search(text)
    if m:
        try:
            return max(0.0, min(1.0, float(m.group(1))))
        except ValueError:
            pass
    return 0.0


def _extract_explanation(text: str) -> str:
    m = _EXPLANATION.search(text)
    if m:
        return m.group(1).strip()
    # Fallback: return the text with the score line removed
    return strip_score_from_reply(text)
