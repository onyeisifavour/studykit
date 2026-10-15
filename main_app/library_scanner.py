"""
library_scanner.py
Walks the learning library root (X/) and returns a structured topic tree.

Expected structure:
    X/
      Subject1/
        Topic1/
          question_bank.txt
          answer_bank.txt
          concept_block.json
          simulations/          ← optional
            sim_name/
              README.md
              (code files)
        Topic2/
          ...
      Subject2/
        ...
"""

import json
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

_log = logging.getLogger(__name__)


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class SimulationInfo:
    name: str
    folder_path: Path
    readme_path: Optional[Path]
    code_files: list[Path] = field(default_factory=list)

    def read_readme(self) -> str:
        if self.readme_path and self.readme_path.exists():
            return self.readme_path.read_text(encoding='utf-8')
        return ''


@dataclass
class TopicInfo:
    name: str
    subject: str
    folder_path: Path
    question_bank_path: Optional[Path]
    answer_bank_path: Optional[Path]
    concept_block_path: Optional[Path]
    simulations: list[SimulationInfo] = field(default_factory=list)

    @property
    def has_simulations(self) -> bool:
        return len(self.simulations) > 0

    @property
    def is_valid(self) -> bool:
        """Minimum requirement: both question and answer banks must exist."""
        return (
            self.question_bank_path is not None
            and self.answer_bank_path is not None
        )

    @property
    def display_label(self) -> str:
        return f"{self.subject}  /  {self.name}"


@dataclass
class LibraryTree:
    root_path: Path
    # { subject_name: { topic_name: TopicInfo } }
    subjects: dict[str, dict[str, TopicInfo]] = field(default_factory=dict)

    def all_topics(self) -> list[TopicInfo]:
        result = []
        for topic_dict in self.subjects.values():
            result.extend(topic_dict.values())
        return result

    def valid_topics(self) -> list[TopicInfo]:
        return [t for t in self.all_topics() if t.is_valid]

    def get_topic(self, subject: str, topic: str) -> Optional[TopicInfo]:
        return self.subjects.get(subject, {}).get(topic)

    def subject_names(self) -> list[str]:
        return sorted(self.subjects.keys())

    def topic_names(self, subject: str) -> list[str]:
        return sorted(self.subjects.get(subject, {}).keys())


# ── Scanner ───────────────────────────────────────────────────────────────────

def scan_library(root_path: str | Path) -> LibraryTree:
    """
    Scans the library root and returns a LibraryTree.
    Raises FileNotFoundError if the root doesn't exist.
    """
    root = Path(root_path)
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(f"Library root not found: {root}")

    tree = LibraryTree(root_path=root)

    for subject_dir in sorted(root.iterdir()):
        if not subject_dir.is_dir() or subject_dir.name.startswith('.'):
            continue

        subject_name = subject_dir.name
        tree.subjects[subject_name] = {}

        for topic_dir in sorted(subject_dir.iterdir()):
            if not topic_dir.is_dir() or topic_dir.name.startswith('.'):
                continue

            topic_name = topic_dir.name
            topic = _scan_topic(subject_name, topic_name, topic_dir)
            tree.subjects[subject_name][topic_name] = topic

    return tree


def _scan_topic(subject: str, name: str, folder: Path) -> TopicInfo:
    q_bank   = _find_file(folder, ['question_bank.txt', 'questions_bank.txt'])
    a_bank   = _find_file(folder, ['answer_bank.txt',   'answers_bank.txt'])
    concept  = _find_file(folder, ['concept_block.json'])
    sims     = _scan_simulations(folder / 'simulations')

    return TopicInfo(
        name=name,
        subject=subject,
        folder_path=folder,
        question_bank_path=q_bank,
        answer_bank_path=a_bank,
        concept_block_path=concept,
        simulations=sims,
    )


def _scan_simulations(sim_dir: Path) -> list[SimulationInfo]:
    if not sim_dir.exists() or not sim_dir.is_dir():
        return []

    sims = []
    for sim_folder in sorted(sim_dir.iterdir()):
        if not sim_folder.is_dir() or sim_folder.name.startswith('.'):
            continue

        readme = sim_folder / 'README.md'
        code_files = [
            f for f in sim_folder.iterdir()
            if f.is_file() and f.suffix in ('.py', '.html', '.js', '.ts')
        ]
        sims.append(SimulationInfo(
            name=sim_folder.name,
            folder_path=sim_folder,
            readme_path=readme if readme.exists() else None,
            code_files=sorted(code_files),
        ))
    return sims


def _find_file(directory: Path, candidates: list[str]) -> Optional[Path]:
    for name in candidates:
        p = directory / name
        if p.exists():
            return p
    return None


# ── File loaders ──────────────────────────────────────────────────────────────

def load_topic_files(topic: TopicInfo) -> dict:
    """
    Reads all file contents for a topic into memory.

    Returns:
        {
          'topic_name':      str,
          'subject_name':    str,
          'questions_text':  str,
          'answers_text':    str,
          'concept_block':   str,   ← raw JSON string
          'question_bank_path': str | None,
          'answer_bank_path':   str | None,
          'concept_block_path': str | None,
          'sim_readmes': [
              {'name': str, 'content': str, 'folder_path': str},
              ...
          ],
        }
    """
    result: dict = {
        'topic_name':     topic.name,
        'subject_name':   topic.subject,
        'questions_text': '',
        'answers_text':   '',
        'concept_block':  '',
        'question_bank_path': str(topic.question_bank_path.resolve()) if topic.question_bank_path else None,
        'answer_bank_path': str(topic.answer_bank_path.resolve()) if topic.answer_bank_path else None,
        'concept_block_path': str(topic.concept_block_path.resolve()) if topic.concept_block_path else None,
        'sim_readmes':    [],
    }

    if topic.question_bank_path:
        result['questions_text'] = topic.question_bank_path.read_text(encoding='utf-8')

    if topic.answer_bank_path:
        result['answers_text'] = topic.answer_bank_path.read_text(encoding='utf-8')

    if topic.concept_block_path:
        result['concept_block'] = topic.concept_block_path.read_text(encoding='utf-8')

    for sim in topic.simulations:
        readme_content = sim.read_readme()
        if readme_content:
            result['sim_readmes'].append({
                'name':        sim.name,
                'content':     readme_content,
                'folder_path': str(sim.folder_path),
            })

    return result


def load_selected_topics(topic_paths: list[str]) -> list[dict]:
    """
    Given a list of topic folder paths (from session config),
    loads and returns the file data for each.
    Skips paths that no longer exist or are invalid.

    Skipped paths are logged. Silent skipping is what let a stale
    ``library_root`` turn a non-empty selection into an empty topic set and
    produce an opaque generation failure downstream.
    """
    results = []
    skipped: list[tuple[str, str]] = []
    for path_str in topic_paths:
        folder = Path(path_str)
        if not folder.exists():
            skipped.append((path_str, 'path does not exist'))
            continue

        subject = folder.parent.name
        name    = folder.name
        topic   = _scan_topic(subject, name, folder)

        if topic.is_valid:
            results.append(load_topic_files(topic))
        else:
            skipped.append((path_str, 'no question/answer bank found'))

    if skipped:
        _log.warning(
            'load_selected_topics: %d of %d selected topic(s) could not be '
            'loaded (check library_root and the saved selection): %s',
            len(skipped), len(topic_paths),
            '; '.join(f'{p} ({why})' for p, why in skipped),
        )

    return results
