"""
user_selections.py

Tracks the student's inferred quiz-intent preferences as a persistent
JSON manifest, extracted each chat turn by a lightweight LLM call.

Design:
  - Each chat turn, the extractor agent reads the conversation + the
    current manifest and returns a JSON *diff* of new/changed fields.
  - The diff is merged into the manifest by Python (not the model),
    so explicit form selections (count=10, toggles) always win over
    chat-derived soft intent.
  - The merged manifest is stored in config and injected into every
    downstream agent prompt as the authoritative "USER SELECTIONS" block,
    replacing raw verbatim chat.
"""

import json
import time
from typing import Any, Optional

from . import config

# ── Schema helpers ────────────────────────────────────────────────────────────

_EMPTY_MANIFEST: dict[str, Any] = {
    'intent': None,          # "quick_test" | "diagnostic" | "prep" | "challenge" | None
    'difficulty': None,      # "basic" | "normal" | "advanced" | None
    'question_count': None,  # explicit count from chat, if student states one
    'count_source': None,    # "form" | "chat" | None
    'style_constraint': None, # "simulation" | "mixed" | None
    'sections': {
        'a_sim': True,
        'a_nonsim': True,
        'b_sim': True,
        'b_nonsim': True,
    },
    'exclusions': [],        # [{topic, reason, from_turn, confidence}]
    'soft_constraints': [],  # [{text, confidence, scope, from_turn}]
    'updated_at': 0,
    'last_turn_processed': -1,
}


def load_manifest() -> dict[str, Any]:
    """Loads the stored manifest from config, returning a fresh copy."""
    raw = config.get('user_selections_manifest')
    if isinstance(raw, dict):
        # Deep copy via JSON round-trip to avoid mutating the stored dict.
        m = json.loads(json.dumps(raw))
        # Ensure all required keys exist (handles partial manifests).
        for k, v in _EMPTY_MANIFEST.items():
            m.setdefault(k, v if not isinstance(v, list) else list(v))
        m.setdefault('sections', dict(_EMPTY_MANIFEST['sections']))
        return m
    return json.loads(json.dumps(_EMPTY_MANIFEST))


def save_manifest(manifest: dict[str, Any]) -> None:
    """Persists the manifest to config."""
    config.set_value('user_selections_manifest', manifest)


def reset_manifest() -> None:
    """Clears the manifest (used when starting a new quiz chat)."""
    save_manifest(json.loads(json.dumps(_EMPTY_MANIFEST)))


# ── Merge ─────────────────────────────────────────────────────────────────────

def merge_manifest(current: dict[str, Any], diff: dict[str, Any],
                   turn_index: int = -1) -> dict[str, Any]:
    """
    Merges an extractor diff into the current manifest.
    Returns a NEW dict (does not mutate ``current``).

    Rules:
      - Explicit form selections (count_source='form') are authoritative;
        chat-derived counts never override them.
      - style_constraint from chat is accepted only if none was set from form.
      - Exclusions are additive and deduplicated by topic.
      - Soft constraints are additive, deduplicated by lowered text, and
        pruned below confidence 0.5.
    """
    m = json.loads(json.dumps(current))

    # Intent: accept if higher-confidence than existing, or existing is None.
    if diff.get('intent'):
        new_conf = diff.get('intent_confidence', 0.8)
        old_conf = m.get('_intent_confidence', 0.0)
        if new_conf >= old_conf or not m.get('intent'):
            m['intent'] = diff['intent']
            m['_intent_confidence'] = new_conf

    # Difficulty: accept if present.
    if diff.get('difficulty'):
        m['difficulty'] = diff['difficulty']

    # Question count: chat-derived only wins if no explicit form selection.
    if diff.get('question_count') is not None:
        src = diff.get('question_count_source', 'chat')
        if src == 'chat' and m.get('count_source') != 'form':
            m['question_count'] = int(diff['question_count'])
            m['count_source'] = 'chat'

    # Style constraint: accept from chat only if not already set from form.
    if diff.get('style_constraint') and not m.get('style_constraint'):
        m['style_constraint'] = diff['style_constraint']

    # Exclusions — additive, deduplicate by topic name (case-insensitive).
    existing_topics = {
        e.get('topic', '').lower().strip()
        for e in m.get('exclusions', [])
    }
    for e in diff.get('exclusions', []):
        key = e.get('topic', '').lower().strip()
        if key and key not in existing_topics and e.get('confidence', 1.0) >= 0.6:
            m.setdefault('exclusions', []).append({
                'topic': e['topic'],
                'reason': e.get('reason', ''),
                'from_turn': e.get('from_turn', turn_index),
                'confidence': e.get('confidence', 0.9),
            })
            existing_topics.add(key)

    # Soft constraints — additive, deduplicate by lowered text.
    existing_soft = {
        s.get('text', '').lower().strip()
        for s in m.get('soft_constraints', [])
    }
    for s in diff.get('soft_constraints', []):
        txt = s.get('text', '').lower().strip()
        if txt and txt not in existing_soft and s.get('confidence', 1.0) >= 0.5:
            m.setdefault('soft_constraints', []).append({
                'text': s['text'],
                'confidence': s.get('confidence', 0.8),
                'scope': s.get('scope', 'general'),
                'from_turn': s.get('from_turn', turn_index),
            })
            existing_soft.add(txt)

    # Prune stale low-confidence items.
    m['exclusions'] = [
        e for e in m.get('exclusions', [])
        if e.get('confidence', 0) >= 0.6
    ]
    m['soft_constraints'] = [
        s for s in m.get('soft_constraints', [])
        if s.get('confidence', 0) >= 0.5
    ]

    m['updated_at'] = int(time.time())
    if turn_index >= 0:
        m['last_turn_processed'] = turn_index
    return m


# ── Request block builder ─────────────────────────────────────────────────────

def build_request_block(manifest: dict[str, Any],
                        fallback_raw: str,
                        form_prefs: Optional[dict] = None) -> str:
    """
    Renders the authoritative USER SELECTIONS block injected into every
    downstream agent prompt (quota planner, 5c audit, etc.).

    Sections plan:
      1. Manifest JSON (authoritative — agent must follow)
      2. Section preferences from the form (overlaid, not duplicated in manifest)
      3. Reference chat message (informational, not authoritative)

    The manifest is the single source of truth. Section toggles from the form
    are injected here explicitly because they live in the Settings UI rather
    than being extracted from chat.
    """
    # Inject form section toggles into the manifest rendering.
    m = dict(manifest)
    sections = dict(m.get('sections', {}))
    if form_prefs:
        for k in ('section_a_sim', 'section_a_nonsim',
                   'section_b_sim', 'section_b_nonsim'):
            # form keys use snake_case; manifest uses short keys.
            short = k.replace('section_', '').replace('_', '_')
            # Map: section_a_sim → a_sim, section_a_nonsim → a_nonsim, etc.
            short_key = k.split('_', 1)[-1].replace('_', '_') if '_' in k else k
            # Simpler: directly map.
            mapping = {
                'section_a_sim': 'a_sim',
                'section_a_nonsim': 'a_nonsim',
                'section_b_sim': 'b_sim',
                'b_nonsim': 'b_nonsim',
            }
            manifest_key = mapping.get(k, k)
            sections[manifest_key] = bool(form_prefs.get(k, True))
    m['sections'] = sections

    # Remove internal keys from JSON rendering.
    render = {k: v for k, v in m.items() if not k.startswith('_')}

    parts = [
        "=== USER SELECTIONS (authoritative — follow these exactly) ===",
        json.dumps(render, indent=2),
        "",
        "=== SECTION PREFERENCES (from form — overrides manifest sections if present) ===",
        _format_sections(form_prefs or {}),
    ]

    if fallback_raw and fallback_raw.strip():
        parts.append("")
        parts.append("=== REFERENCE CHAT MESSAGE (informational) ===")
        parts.append(fallback_raw.strip())

    return "\n".join(parts)


def _format_sections(prefs: dict) -> str:
    lines = []
    if prefs.get('section_a_sim'):
        lines.append("* Section A (Objective): Simulation questions included")
    if prefs.get('section_a_nonsim'):
        lines.append("* Section A (Objective): Non-simulation questions included")
    if prefs.get('section_b_sim'):
        lines.append("* Section B (Theory): Simulation questions included")
    if prefs.get('section_b_nonsim'):
        lines.append("* Section B (Theory): Non-simulation questions included")
    return "\n".join(lines) if lines else "(no section preferences set)"


# ── Machine-checked audit ─────────────────────────────────────────────────────

def check_manifest_against_plan(manifest: dict[str, Any],
                                sequence_manifest: dict) -> list[str]:
    """
    Deterministic checks comparing the manifest against a quiz plan.
    Returns a list of violation strings (empty = all pass).

    These are run BEFORE the LLM audit, and their violations are fed
    into the audit prompt so 5c can focus on soft constraints only.
    """
    violations: list[str] = []
    seq = sequence_manifest.get('ordered_quiz_sequence', [])
    total = sequence_manifest.get('total_questions', len(seq))

    # 1. Question count: check config (authoritative form value), then manifest.
    #    config.get('question_count') is the UI form count; manifest tracks
    #    explicit chat-stated counts (count_source='chat').
    expected: int | None = None
    source_label = 'form-selected'
    cfg_count = config.get('question_count')
    if cfg_count is not None:
        expected = int(cfg_count)
    elif manifest.get('question_count') is not None:
        expected = int(manifest['question_count'])
        source_label = f"manifest (source={manifest.get('count_source', '?')})"
    if expected is not None and total != expected:
        violations.append(
            f"Plan has {total} questions but the {source_label} count is {expected}."
        )

    # 2. Section composition: if all nonsim disabled, every slot must be Sim.
    sections = manifest.get('sections', {})
    nonsim_disabled = not sections.get('a_nonsim', True) and not sections.get('b_nonsim', True)
    if nonsim_disabled:
        for slot in seq:
            fmt = slot.get('format', 'Non-Sim')
            if fmt == 'Non-Sim':
                violations.append(
                    f"Slot {slot.get('slot_number')}: format is '{fmt}' but "
                    "section preferences disable non-simulation questions."
                )

    # 3. Exclusions: no excluded topic should appear in the plan.
    excl_topics = {e.get('topic', '').lower().strip()
                   for e in manifest.get('exclusions', [])
                   if e.get('confidence', 0) >= 0.6}
    for slot in seq:
        slot_topic = (slot.get('topic', '') or '').lower().strip()
        if slot_topic in excl_topics:
            violations.append(
                f"Slot {slot.get('slot_number')}: topic '{slot.get('topic')}' "
                "is in the user's exclusions list."
            )

    return violations


# ── Math-notation check (deterministic) ───────────────────────────────────────

import re as _re

_MATH_ASCII_PATTERNS = {
    'caret_exponent': {
        'pattern': _re.compile(
            r'(?<![\$])(?<![A-Za-z0-9}])\^(?=[0-9])|(?<![A-Za-z])\^\d'
        ),
        'hint': 'write as $...^{...}$ or $\\times10^{...}$',
    },
    'x_as_times': {
        'pattern': _re.compile(r'\d\s*[\u00d7x]\s*\d'),
        'hint': 'write × inside math as $\\times$',
    },
    'asterisk_times': {
        'pattern': _re.compile(r'\d\s*\*\s*\d'),
        'hint': 'write multiplication as $\\times$',
    },
}


def _scan_text(text: str, where: str, violations: list[str]) -> None:
    if not isinstance(text, str) or not text.strip():
        return
    stripped = _strip_math_spans(text)
    for name, spec in _MATH_ASCII_PATTERNS.items():
        if spec['pattern'].search(stripped):
            excerpt = text.strip().replace('\n', ' ')[:140]
            violations.append(
                f"[{where}] uses plain-ASCII math ({name}): {excerpt!r}. "
                f"Instead, {spec['hint']}."
            )


def _protected_blocks(text: str) -> list[tuple[str, bool]]:
    """Splits text into (chunk, is_protected_math) pairs, where protected
    spans are already-delimited LaTeX (``$..$``, ``$$..$$``,
    ``\\begin{equation}..\\end{equation}``, ``\\(..\\)``, ``\\[..\\]``).
    The checker and the normalizer must never touch protected spans."""
    _PROTECT = _re.compile(
        r'\$\$.+?\$\$'
        r'|\\begin\{equation\}.*?\\end\{equation\}'
        r'|\$[^$\n]+\$'
        r'|\\\(.*?\\\)'
        r'|\\\[.*?\\\]',
        flags=_re.S,
    )
    parts: list[tuple[str, bool]] = []
    last = 0
    for m in _PROTECT.finditer(text):
        if m.start() > last:
            parts.append((text[last:m.start()], False))
        parts.append((m.group(0), True))
        last = m.end()
    if last < len(text):
        parts.append((text[last:], False))
    return parts


def _strip_math_spans(text: str) -> str:
    """Removes already-delimited math so the checker ignores compliant output."""
    return ''.join(' MATH ' if protected else chunk
                   for chunk, protected in _protected_blocks(text))


def check_math_notation(sequence_manifest: dict) -> list[str]:
    """
    Deterministic check that AI-authored (Sim-format) question text is written
    as delimited LaTeX math, not plain ASCII (`10^26`, `x` as times, `a*b`).

    Only Sim-format questions are scanned: those are authored by the pipeline's
    sim generator, so the output must obey MATH_NOTATION_SPEC. Bank-copied
    (Non-Sim) text is verbatim and skipped to avoid false failures.

    Returns a list of violation strings (empty = all pass).
    """
    violations: list[str] = []
    for slot in sequence_manifest.get('ordered_quiz_sequence', []):
        q = slot.get('question', {}) or {}
        if not isinstance(q, dict):
            continue
        if str(q.get('format', 'Non-Sim')) != 'Sim':
            continue
        slot_label = f"Sim slot {slot.get('sequence_index', '?')}"
        _scan_text(q.get('text') or '', f'{slot_label} question', violations)
        for i, opt in enumerate(q.get('options') or [], start=1):
            _scan_text(opt, f'{slot_label} option {i}', violations)
        _scan_text(q.get('correct_answer') or '', f'{slot_label} correct_answer', violations)
        _scan_text(q.get('sim_instruction') or '', f'{slot_label} sim_instruction', violations)
    return violations


# ── ASCII-math normalizer ──────────────────────────────────────────────────────

_MATH_RUN_CHARS = frozenset('0123456789.eE+-\u2212/()\u00d7x*^{} \t')

_MATH_TRIGGERS = [
    # numerics-power forms: 10^25, (1/2)^2, ^-3
    _re.compile(r'\^\{[^}]*\}|\^\([^)]*\)|\^[-+]?\d+'),
    # variable-power forms: r^2, v^{2}
    _re.compile(r'\^\{[^}]*\}|\^[A-Za-z](?![A-Za-z0-9{])'),
    # multiplication as x/× between numbers
    _re.compile(r'\d\s*[\u00d7x]\s*\d'),
    # multiplication as * between numbers
    _re.compile(r'\d\s*\*\s*\d'),
]


def _mathify_run(run: str) -> str:
    """Rewrites one contiguous plain-ASCII math run into LaTeX."""
    t = _re.sub(r'\s*[\u00d7x]\s*', r'\\times', run)
    t = _re.sub(r'\s*\*\s*', r'\\times', t)
    # exponent forms → ^{...}
    t = _re.sub(r'\^\(([^)]*)\)', r'^{\1}', t)
    t = _re.sub(r'\^\{([^}]*)\}', r'^{\1}', t)
    t = _re.sub(r'\^([-+]?\d+|[A-Za-z])', r'^{\1}', t)
    return t


def _first_math_trigger(text: str, pos: int):
    best = None
    for pat in _MATH_TRIGGERS:
        m = pat.search(text, pos)
        if m and (best is None or m.start() < best.start()):
            best = m
    return best


def normalize_ascii_math(text: str) -> str:
    """
    Deterministic, conservative display-only repair: wraps the worst plain-ASCII
    math (`1.18 x 10^25 x (1.0/0.5)^2`, `r^2`, `a*b`) into delimited LaTeX so
    the KaTeX renderer displays it neatly even when the authoring AI did not
    follow MATH_NOTATION_SPEC. Already-delimited math spans are left untouched.

    Returns the repaired text. Runs only on numeric/variable patterns, so any
    prose containing digits, `x`, `*` or `^` for other purposes is unaffected.
    """
    if not isinstance(text, str) or not text.strip():
        return text
    out: list[str] = []
    for chunk, protected in _protected_blocks(text):
        if protected:
            out.append(chunk)
            continue
        if not any(p.search(chunk) for p in _MATH_TRIGGERS):
            out.append(chunk)
            continue
        repaired: list[str] = []
        pos = 0
        while True:
            m = _first_math_trigger(chunk, pos)
            if m is None:
                repaired.append(chunk[pos:])
                break
            start, end = m.start(), m.end()
            while start > pos and chunk[start - 1] in _MATH_RUN_CHARS:
                start -= 1
            while end < len(chunk) and chunk[end] in _MATH_RUN_CHARS:
                end += 1
            # Never swallow sentence whitespace/punctuation at the boundaries.
            while start < end and (chunk[start].isspace()
                                   or chunk[start] in ',.:;!?'):
                start += 1
            while end > start and (chunk[end - 1].isspace()
                                   or chunk[end - 1] in ',.:;!?'):
                end -= 1
            repaired.append(chunk[pos:start])
            run = chunk[start:end]
            if run:
                repaired.append('$' + _mathify_run(run) + '$')
            pos = end
        out.append(''.join(repaired))
    return ''.join(out)


# ── LLM extractor ─────────────────────────────────────────────────────────────

EXTRACTOR_SYSTEM = """\
You are a preference-extraction agent. Given a conversation between an AI \
tutor and a student, extract the student's explicit and inferred quiz \
preferences into JSON.

Output ONLY a JSON object with this exact shape (no markdown, no prose):

{
  "intent": "quick_test" | "diagnostic" | "prep" | "challenge" | null,
  "difficulty": "basic" | "normal" | "advanced" | null,
  "question_count": integer | null,
  "question_count_source": "chat" | null,
  "style_constraint": "simulation" | "mixed" | null,
  "intent_confidence": float,
  "exclusions": [{"topic": string, "reason": string, "from_turn": int, "confidence": float}],
  "soft_constraints": [{"text": string, "confidence": float, "scope": "question_type"|"topic"|"style"|"general", "from_turn": int}]
}

Rules:
- intent: infer from context. "quick quiz" / "just testing" → quick_test. \
"never took the subject" is NOT an intent. \
"preparing for exam" → prep. "I want challenge" → challenge.
- difficulty: explicit if stated. "normal level not basics" → normal. \
If unstated, null.
- question_count: ONLY if the student explicitly states a number \
("give me 5 questions", "just 3"). If they say "quick" without a number, \
leave null.
- style_constraint: ONLY if the student explicitly mentions simulation \
preference ("I want hands-on", "no simulation"). If unstated, null.
- intent_confidence: 1.0 for explicit statements, 0.7-0.9 for strong \
inferences, 0.5-0.7 for weak hints.
- exclusions: ONLY if the student explicitly says "no X" or "don't want X" \
on a topic/type. confidence ≥ 0.8 for explicit, 0.6-0.7 for implied.
- soft_constraints: things like "I'd prefer more of these questions", \
"less maths-heavy", "focus on X". Each must have scope.
- If the conversation has no student preferences at all (just greetings), \
return null values and empty arrays.
- Do NOT repeat information already in the current manifest; only output \
fields that are NEW or CHANGED relative to it."""

EXTRACTOR_USER = """\
<conversation>
{conversation}
</conversation>

<current_manifest>
{current_manifest}
</current_manifest>

Extract any NEW or UPDATED preferences from the student's messages. \
Return ONLY the JSON diff object. Do not repeat fields already present \
in the current manifest with identical values."""


def extract_manifest_diff(conversation: str,
                          current_manifest: dict[str, Any],
                          cli_client,
                          timeout: float = 20.0) -> Optional[dict[str, Any]]:
    """
    Calls the extractor prompt via CLIBridgeClient (stateless, no agent).
    Returns the parsed JSON diff, or None on failure.
    """
    from .api_client import CLIBridgeClient

    result_holder: dict[str, Any] = {}

    def _on_success(text: str, _new_sid: str) -> None:
        # Strip markdown fences if present.
        cleaned = text.strip()
        if cleaned.startswith('```'):
            lines = cleaned.split('\n')
            lines = [l for l in lines if not l.startswith('```')]
            cleaned = '\n'.join(lines).strip()
        try:
            result_holder['diff'] = json.loads(cleaned)
        except (json.JSONDecodeError, TypeError):
            result_holder['diff'] = None

    def _on_error(msg: str) -> None:
        result_holder['error'] = msg

    # Render prompts.
    conv_text = conversation if isinstance(conversation, str) else json.dumps(conversation, indent=2)
    manifest_text = json.dumps(current_manifest, indent=2)
    user_prompt = EXTRACTOR_USER.format(
        conversation=conv_text,
        current_manifest=manifest_text,
    )

    cli_client.call(
        agent=None,
        session_id=None,
        system=EXTRACTOR_SYSTEM,
        user=user_prompt,
        on_success=_on_success,
        on_error=_on_error,
    )

    # Block until done (polling).
    deadline = time.time() + timeout
    while 'diff' not in result_holder and 'error' not in result_holder:
        if time.time() > deadline:
            return None
        time.sleep(0.05)

    return result_holder.get('diff')
