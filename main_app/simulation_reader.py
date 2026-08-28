"""
simulation_reader.py

Reads simulation README files and formats them for inclusion in AI prompts.
The AI uses these to understand each simulation well enough to:
  - Generate appropriate simulation-based questions.
  - Specify exact parameter values for students to set.
  - Produce correct expected answers.
"""

from pathlib import Path
from typing import Optional


# ── Single README ─────────────────────────────────────────────────────────────

def read_readme(sim_folder: Path) -> Optional[str]:
    """Reads README.md from a simulation folder. Returns None if not found."""
    readme = sim_folder / 'README.md'
    return readme.read_text(encoding='utf-8') if readme.exists() else None


# ── Formatting for prompts ────────────────────────────────────────────────────

def build_sim_context_block(sim_readmes: list[dict]) -> str:
    """
    Formats a list of simulation README dicts into a single labelled block
    for injection into AI prompts.

    sim_readmes: list of {'name': str, 'content': str, 'folder_path': str}

    Output format:
        === SIMULATION 1: <name> ===
        <readme content>
        === END SIMULATION 1 ===

        === SIMULATION 2: <name> ===
        ...
    """
    if not sim_readmes:
        return "No simulations available for the selected topics."

    blocks: list[str] = []
    for i, sim in enumerate(sim_readmes, start=1):
        block = (
            f"=== SIMULATION {i}: {sim['name']} ===\n"
            f"{sim['content'].strip()}\n"
            f"=== END SIMULATION {i} ==="
        )
        blocks.append(block)

    return "\n\n".join(blocks)


def collect_sim_readmes(topic_files: list[dict]) -> list[dict]:
    """
    Gathers all simulation README dicts from a list of loaded topic files,
    adding the parent topic name to each entry.

    Returns a flat list of:
        {'name': str, 'content': str, 'folder_path': str, 'topic': str}
    """
    all_readmes: list[dict] = []
    for tf in topic_files:
        for sim in tf.get('sim_readmes', []):
            all_readmes.append({**sim, 'topic': tf['topic_name']})
    return all_readmes


def has_simulations(topic_files: list[dict]) -> bool:
    """Returns True if any of the selected topics have simulation READMEs."""
    return any(tf.get('sim_readmes') for tf in topic_files)
