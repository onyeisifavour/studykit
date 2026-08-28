"""
blueprint_generator.py

Parses the AI blueprint response (Call 1 output) into a structured Blueprint object.

BlueprintEntry is defined in question_generator.py to avoid duplication
(question_generator also uses it when assembling the final question list).

Blueprint line format produced by the AI:
    Q01 | MCQ  | A | Physics: Newton's Laws | NO_SIM
    Q02 | SUBJ | B | Chemistry: Acids       | NO_SIM
    Q03 | MCQ  | A | Physics: Projectile    | SIM:projectile_motion | SET:1
    Q04 | SUBJ | B | Physics: Projectile    | SIM:projectile_motion | SET:1
    Q05 | MCQ  | A | Chemistry: Acids       | NO_SIM

IMPORTANT: Type (MCQ/SUBJ) and simulation status are independent axes.
Section A is always MCQ, Section B is always SUBJ — that pairing is fixed.
But EITHER type can be a simulation question: an MCQ can ask the student to
run a simulation, take a measurement, and pick the matching option from a
generated list. The 5th field (NO_SIM / SIM:<folder>) is what determines
whether a question is a simulation question — never the type field.
"""

import re
import dataclasses
from dataclasses import dataclass, field
from typing import Optional

from .question_generator import BlueprintEntry


# ── Blueprint container ───────────────────────────────────────────────────────

@dataclass
class Blueprint:
    entries:  list[BlueprintEntry]
    raw_text: str = ''

    # ── Derived views ─────────────────────────────────────────────────────────

    @property
    def total(self) -> int:
        return len(self.entries)

    def sim_slot_indices(self) -> list[int]:
        """0-based indices of simulation question slots."""
        return [i for i, e in enumerate(self.entries) if e.is_simulation]

    def non_sim_slot_indices(self) -> list[int]:
        """0-based indices of non-simulation question slots."""
        return [i for i, e in enumerate(self.entries) if not e.is_simulation]

    def get_sim_sets(self) -> dict[int, list[int]]:
        """
        Groups simulation entries by their SET number.
        Returns { set_num: [0-based index, ...] }
        """
        sets: dict[int, list[int]] = {}
        for i, e in enumerate(self.entries):
            if e.is_simulation:
                sets.setdefault(e.sim_set, []).append(i)
        return sets

    def sim_slot_count_for_set(self, set_num: int) -> int:
        """How many simulation slots belong to a given SET."""
        return sum(
            1 for e in self.entries
            if e.is_simulation and e.sim_set == set_num
        )

    def unique_sim_names(self) -> list[str]:
        """Distinct simulation folder names used in this blueprint."""
        seen:   set[str]  = set()
        result: list[str] = []
        for e in self.entries:
            if e.is_simulation and e.sim_name and e.sim_name not in seen:
                seen.add(e.sim_name)
                result.append(e.sim_name)
        return result

    def has_simulations(self) -> bool:
        return any(e.is_simulation for e in self.entries)

    def topic_names(self) -> list[str]:
        """Ordered list of unique topic labels from the blueprint."""
        seen:   set[str]  = set()
        result: list[str] = []
        for e in self.entries:
            if e.topic and e.topic not in seen:
                seen.add(e.topic)
                result.append(e.topic)
        return result


# ── Parser ────────────────────────────────────────────────────────────────────

# Matches: Q01 | MCQ  | A | Topic Name | NO_SIM
#      or: Q03 | MCQ  | A | Topic Name | SIM:folder_name | SET:1
#      or: Q04 | SUBJ | B | Topic Name | SIM:folder_name | SET:1
# Type is ALWAYS MCQ or SUBJ. Simulation status comes only from field 5.
_BP_LINE = re.compile(
    r'^(Q\d+)\s*\|\s*(MCQ|SUBJ)\s*\|\s*([AB])\s*\|'
    r'\s*([^|]+?)\s*\|\s*(NO_SIM|SIM:[^\s|]+)'
    r'(?:\s*\|\s*SET:(\d+))?',
    re.IGNORECASE,
)


def parse_blueprint(raw_text: str) -> Blueprint:
    """
    Parses the AI-generated blueprint text into a Blueprint object.

    Extracts content between BLUEPRINT_START / BLUEPRINT_END markers.
    Falls back to scanning the full text if markers are absent.
    Lines that do not match the expected format are silently skipped.
    """
    if not raw_text or not isinstance(raw_text, str):
        return Blueprint(entries=[], raw_text=raw_text or '')

    content = _extract_content(raw_text)
    entries: list[BlueprintEntry] = []

    for line in content.splitlines():
        entry = _parse_line(line.strip())
        if entry is not None:
            entries.append(entry)

    return Blueprint(entries=entries, raw_text=raw_text)


def _parse_line(line: str) -> Optional[BlueprintEntry]:
    """Parses one blueprint line. Returns None if the line doesn't match."""
    m = _BP_LINE.match(line)
    if not m:
        return None

    q_code, q_type, section, topic, sim_field, sim_set_str = m.groups()

    q_type   = q_type.upper()
    is_sim   = sim_field.upper().startswith('SIM:')
    sim_name = sim_field[4:].strip() if is_sim else ''

    number = int(re.sub(r'\D', '', q_code))

    return BlueprintEntry(
        number=number,
        q_code=q_code.upper(),
        q_type=q_type,
        section=section.upper(),
        topic=topic.strip(),
        is_simulation=is_sim,
        sim_name=sim_name,
        sim_set=int(sim_set_str) if sim_set_str else 0,
    )


def _extract_content(text: str) -> str:
    """Returns text between BLUEPRINT_START and BLUEPRINT_END, or full text."""
    start_marker = 'BLUEPRINT_START'
    end_marker   = 'BLUEPRINT_END'
    s = text.find(start_marker)
    e = text.find(end_marker)
    if s != -1 and e != -1:
        return text[s + len(start_marker): e]
    return text


# ── Hard question-type enforcement ────────────────────────────────────────────

def apply_type_filters(
    blueprint: Blueprint,
    allow_mcq: bool,
    allow_subj: bool,
    allow_sim: bool,
) -> Blueprint:
    """
    Hard-enforces Settings' question-type filters on an already-parsed
    blueprint. The AI is told about the constraint in the prompt too, but
    small/fast models (e.g. GROQ's Llama models) don't reliably obey format
    or content constraints — this strips anything that slips through before
    it ever reaches a downstream API call. Entries are renumbered
    sequentially afterward so Q-codes stay contiguous, and raw_text is
    rebuilt so every later prompt reflects the ENFORCED blueprint, not
    whatever the AI originally proposed.
    """
    kept = []
    for e in blueprint.entries:
        if e.q_type == 'MCQ' and not allow_mcq:
            continue
        if e.q_type == 'SUBJ' and not allow_subj:
            continue
        if e.is_simulation and not allow_sim:
            continue
        kept.append(e)

    renumbered = [
        dataclasses.replace(e, number=i, q_code=f"Q{i:02d}")
        for i, e in enumerate(kept, start=1)
    ]
    return Blueprint(entries=renumbered, raw_text=_rebuild_blueprint_text(renumbered))


def apply_section_filters(
    blueprint: Blueprint,
    section_a_sim: bool,
    section_a_nonsim: bool,
    section_b_sim: bool,
    section_b_nonsim: bool,
) -> Blueprint:
    """
    Hard-enforces Settings' section-based question-type filters on an
    already-parsed blueprint. Each section (A=Objective, B=Theory) can
    independently include simulation and/or non-simulation questions.
    Entries are renumbered sequentially afterward so Q-codes stay contiguous.
    """
    kept = []
    for e in blueprint.entries:
        if e.section == 'A':  # MCQ
            if e.is_simulation and not section_a_sim:
                continue
            if not e.is_simulation and not section_a_nonsim:
                continue
        elif e.section == 'B':  # SUBJ
            if e.is_simulation and not section_b_sim:
                continue
            if not e.is_simulation and not section_b_nonsim:
                continue
        kept.append(e)

    renumbered = [
        dataclasses.replace(e, number=i, q_code=f"Q{i:02d}")
        for i, e in enumerate(kept, start=1)
    ]
    return Blueprint(entries=renumbered, raw_text=_rebuild_blueprint_text(renumbered))


def _rebuild_blueprint_text(entries: list[BlueprintEntry]) -> str:
    """Reconstructs blueprint text in the standard format from a filtered/
    renumbered entry list, so downstream prompts see the enforced version."""
    lines = ["BLUEPRINT_START"]
    for e in entries:
        sim_field = f"SIM:{e.sim_name}" if e.is_simulation else "NO_SIM"
        line = f"{e.q_code} | {e.q_type:<4} | {e.section} | {e.topic} | {sim_field}"
        if e.is_simulation and e.sim_set:
            line += f" | SET:{e.sim_set}"
        lines.append(line)
    lines.append("BLUEPRINT_END")
    return "\n".join(lines)
