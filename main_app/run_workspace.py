"""Durable, inspectable workspace for one quiz-generation run."""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_DEFAULT_RETENTION = 20


def runs_root() -> Path:
    root = Path(os.environ.get('QUIZ_APP_HOME', Path.home() / '.quiz_app'))
    return (root / 'runs').expanduser().resolve()


def retention_limit() -> int:
    """How many runs to keep. Overridable via QUIZ_APP_RUN_RETENTION."""
    raw = os.environ.get('QUIZ_APP_RUN_RETENTION', '').strip()
    if raw:
        try:
            limit = int(raw)
            if limit > 0:
                return limit
        except ValueError:
            pass
    return _DEFAULT_RETENTION


def new_run(metadata: dict[str, Any] | None = None) -> Path:
    run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}"
    run = runs_root() / run_id
    run.mkdir(parents=True, exist_ok=False)
    write(run, 'run.json', {
        'run_id': run_id,
        'created': datetime.now(timezone.utc).isoformat(),
        **(metadata or {}),
    })
    # Keep the run directory from growing without bound. The newest runs are
    # kept (ordered by mtime, so runs created in the same second are still
    # ordered correctly); the run just created is never pruned.
    prune_runs(protect=run)
    return run


def prune_runs(keep: int | None = None, protect: Path | None = None) -> list[Path]:
    """Deletes all but the newest `keep` runs. Returns the removed paths.

    `protect` (the run just created) is never removed, even if `keep` is 1.
    """
    limit = retention_limit() if keep is None else keep
    if limit <= 0:
        return []
    root = runs_root()
    if not root.exists():
        return []

    def _recency(path: Path) -> tuple[int, str]:
        try:
            mtime = path.stat().st_mtime_ns
        except OSError:
            mtime = 0
        return (mtime, path.name)

    candidates = sorted(
        (p for p in root.iterdir() if p.is_dir()),
        key=_recency,
        reverse=True,
    )
    keep_names = {p.name for p in candidates[:limit]}
    if protect is not None:
        keep_names.add(protect.name)
    removed: list[Path] = []
    for path in candidates:
        if path.name not in keep_names:
            cleanup(path)
            removed.append(path)
    return removed


def write(run: Path, name: str, data: Any) -> Path:
    if isinstance(data, str):
        return write_text(run, name, data)
    return write_text(run, name, json.dumps(data, indent=2, ensure_ascii=False))


def write_text(run: Path, name: str, data: str) -> Path:
    path = (run / name).resolve()
    if not path.is_relative_to(run.resolve()):
        raise ValueError(f'Artifact path escapes run workspace: {name}')
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f'.{path.name}.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return path


def cleanup(run: Path) -> None:
    import shutil
    shutil.rmtree(run, ignore_errors=True)
