"""
config.py

Persistent app configuration stored at ~/.quiz_app/config.json

Keys used across the app:
    groq_keys           list[str] — up to 4 GROQ API keys
    openrouter_keys     list[str] — up to 4 OpenRouter API keys
    groq_model          str       — GROQ model name used for all GROQ keys
    openrouter_model    str       — OpenRouter model name used for all OR keys
    library_root        str       — path to the X/ learning library folder
    selected_topics     list      — list of topic folder paths chosen in Settings
    evaluation_on       bool      — evaluation toggle default
    custom_api_url      str       — custom OpenAI-compatible API base URL
    custom_api_key      str       — custom API key
    custom_model        str       — model name for custom provider
    provider_mode       str       — 'api' or 'cli_bridge'
    cli_model           str       — model name for CLI bridge (e.g. 'opencode/big-pickle')
    shuffle_enabled     bool      — shuffle quiz questions (False = keep arc order)
    keep_sim_together   bool      — keep same-sim questions adjacent when shuffling
    question_count      int       — number of questions in a generated quiz
    timer_mode          str       — 'off' | 'perQ' | 'total' quiz countdown mode
    timer_per_q         int       — seconds per question when timer_mode='perQ'
    timer_total         int       — overall minutes when timer_mode='total'
    total_expiry        str       — 'end' | 'continue' when overall time runs out

Durability
----------
Writes go through a temp file + `os.replace` while holding a process- and
POSIX-wide lock, so a concurrent read can never see a truncated file. Every
successful save also refreshes `config.json.bak` (last-known-good). If the live
file is ever unreadable it is quarantined to `config.corrupt-<ts>.json` and the
backup is restored, so settings and the learner-profile session pointers survive
a bad write. Keep `agent_sessions`, `pending_messages` and `current_quiz_id`
intact on every save — they are the durable profile, not per-run state.
"""

import json
import logging
import os
import tempfile
import threading
import time
from pathlib import Path

_log = logging.getLogger(__name__)

_CONFIG_DIR  = Path.home() / '.quiz_app'
_CONFIG_FILE = _CONFIG_DIR / 'config.json'
#: Last-known-good mirror of the config, refreshed on every successful save.
_CONFIG_BAK  = _CONFIG_DIR / 'config.json.bak'

# Every read-modify-write cycle runs under this lock. The thread lock serialises
# callers inside one process (the sidecar runs many worker threads); the flock
# additionally serialises against other processes (e.g. a stray second sidecar).
_THREAD_LOCK = threading.RLock()
try:
    import fcntl as _fcntl
except Exception:  # pragma: no cover - non-POSIX
    _fcntl = None


class _ConfigLock:
    """Re-entrant thread lock + best-effort cross-process advisory lock."""

    def __init__(self) -> None:
        self._fd: int | None = None

    def __enter__(self) -> '_ConfigLock':
        _THREAD_LOCK.acquire()
        if _fcntl is not None:
            try:
                _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
                self._fd = os.open(
                    str(_CONFIG_FILE) + '.lock', os.O_CREAT | os.O_RDWR, 0o600
                )
                _fcntl.flock(self._fd, _fcntl.LOCK_EX)
            except Exception:
                self._close_fd()
        return self

    def __exit__(self, *exc) -> bool:
        self._close_fd()
        _THREAD_LOCK.release()
        return False

    def _close_fd(self) -> None:
        if self._fd is not None:
            try:
                if _fcntl is not None:
                    _fcntl.flock(self._fd, _fcntl.LOCK_UN)
                os.close(self._fd)
            except Exception:
                pass
            self._fd = None


def _atomic_write_text(path: Path, text: str) -> None:
    """Writes `text` to `path` atomically (temp file + fsync + os.replace).

    A reader never observes a half-written file, which is what used to let a
    torn read wipe the config down to a single key.
    """
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(_CONFIG_DIR), prefix='.config-', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        raise


def _recover_unlocked(exc: Exception) -> dict:
    """Handles an unreadable config file.

    Quarantines the broken bytes to `config.corrupt-<ts>.json` so a developer can
    inspect exactly what went wrong, then restores the last-known-good backup if
    one exists. The live file is reseeded so a single corruption does not
    re-quarantine on every subsequent read. Never raises: the app keeps running.
    """
    stamp = time.strftime('%Y%m%d-%H%M%S')
    quarantine = _CONFIG_DIR / f'config.corrupt-{stamp}.json'
    try:
        if _CONFIG_FILE.exists():
            os.replace(str(_CONFIG_FILE), str(quarantine))
    except Exception:
        try:
            quarantine.write_text(
                _CONFIG_FILE.read_text(encoding='utf-8'), encoding='utf-8'
            )
        except Exception:
            pass

    recovered: dict = {}
    source = 'empty config'
    if _CONFIG_BAK.exists():
        try:
            data = json.loads(_CONFIG_BAK.read_text(encoding='utf-8'))
            if isinstance(data, dict):
                recovered = data
                source = 'config.json.bak'
        except Exception:
            recovered = {}

    _log.warning(
        'config.json was unreadable (%s); quarantined to %s and recovered from %s',
        exc, quarantine.name, source,
    )

    try:
        _atomic_write_text(_CONFIG_FILE, json.dumps(recovered, indent=2))
    except Exception:
        pass
    return recovered


def _load_unlocked() -> dict:
    if not _CONFIG_FILE.exists():
        return {}
    try:
        data = json.loads(_CONFIG_FILE.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            raise ValueError('config root is not a JSON object')
        return data
    except Exception as exc:
        return _recover_unlocked(exc)


def _save_unlocked(data: dict) -> None:
    payload = json.dumps(data, indent=2)
    _atomic_write_text(_CONFIG_FILE, payload)
    # Refresh the fallback copy only after the live file is safely in place.
    try:
        _atomic_write_text(_CONFIG_BAK, payload)
    except Exception:
        pass


def load() -> dict:
    """Loads and returns the full config dict.

    A missing file yields {}. An *unreadable* file is quarantined and recovered
    from the last-known-good backup rather than silently becoming {}.
    """
    with _ConfigLock():
        return _load_unlocked()


def save(data: dict) -> None:
    """Overwrites the config file with the given dict (atomically)."""
    with _ConfigLock():
        _save_unlocked(data)


def get(key: str, default=None):
    """Gets a single value by key."""
    with _ConfigLock():
        return _load_unlocked().get(key, default)


def set_value(key: str, value) -> None:
    """Sets a single key and persists."""
    with _ConfigLock():
        cfg = _load_unlocked()
        cfg[key] = value
        _save_unlocked(cfg)


def update(updates: dict) -> None:
    """Merges multiple key-value pairs and persists."""
    with _ConfigLock():
        cfg = _load_unlocked()
        cfg.update(updates)
        _save_unlocked(cfg)


# ── Typed convenience accessors ───────────────────────────────────────────────

def get_groq_keys() -> list[str]:
    keys = get('groq_keys', [])
    return (keys + [''] * 4)[:4]


def get_openrouter_keys() -> list[str]:
    keys = get('openrouter_keys', [])
    return (keys + [''] * 4)[:4]


def get_groq_model() -> str:
    return get('groq_model') or ''


def get_openrouter_model() -> str:
    return get('openrouter_model') or ''


def get_library_root() -> str:
    return get('library_root', '')


def get_selected_topics() -> list[str]:
    return get('selected_topics', [])


def get_evaluation_on() -> bool:
    return get('evaluation_on', True)


def save_groq_keys(keys: list[str]) -> None:
    set_value('groq_keys', keys)


def save_openrouter_keys(keys: list[str]) -> None:
    set_value('openrouter_keys', keys)


def save_groq_model(model: str) -> None:
    set_value('groq_model', model)


def save_openrouter_model(model: str) -> None:
    set_value('openrouter_model', model)


def save_library_root(path: str) -> None:
    set_value('library_root', path)


def save_selected_topics(paths: list[str]) -> None:
    set_value('selected_topics', paths)


def save_evaluation_on(value: bool) -> None:
    set_value('evaluation_on', value)


def get_question_type_filters() -> dict:
    """Returns {'mcq': bool, 'subj': bool, 'sim': bool}. Defaults all True."""
    return {
        'mcq':  get('allow_mcq', True),
        'subj': get('allow_subj', True),
        'sim':  get('allow_sim', True),
    }


def save_question_type_filters(mcq: bool, subj: bool, sim: bool) -> None:
    update({'allow_mcq': mcq, 'allow_subj': subj, 'allow_sim': sim})


def get_question_section_preferences() -> dict:
    """Returns section-based question preferences.
    
    Structure:
        section_a_sim: bool   — Section A (Objective) simulation questions
        section_a_nonsim: bool — Section A (Objective) non-simulation questions
        section_b_sim: bool   — Section B (Theory) simulation questions
        section_b_nonsim: bool — Section B (Theory) non-simulation questions
    """
    return {
        'section_a_sim':    get('section_a_sim', True),
        'section_a_nonsim': get('section_a_nonsim', True),
        'section_b_sim':    get('section_b_sim', True),
        'section_b_nonsim': get('section_b_nonsim', True),
    }


def save_question_section_preferences(section_a_sim: bool, section_a_nonsim: bool,
                                       section_b_sim: bool, section_b_nonsim: bool) -> None:
    update({
        'section_a_sim': section_a_sim,
        'section_a_nonsim': section_a_nonsim,
        'section_b_sim': section_b_sim,
        'section_b_nonsim': section_b_nonsim,
    })


def get_shuffle_preferences() -> dict:
    """Returns quiz shuffling preferences.

    Structure:
        shuffle_enabled: bool   — False (default): keep the Agent 4 arc order
                                  (neither non-sim nor sim questions are shuffled)
        keep_sim_together: bool — True: when shuffling, keep same-sim questions
                                  adjacent as one block
    """
    return {
        'shuffle_enabled': get('shuffle_enabled', False),
        'keep_sim_together': get('keep_sim_together', True),
    }


def save_shuffle_preferences(shuffle_enabled: bool, keep_sim_together: bool) -> None:
    update({
        'shuffle_enabled': shuffle_enabled,
        'keep_sim_together': keep_sim_together,
    })


def get_last_skip_mode() -> str:
    """'zero' or 'exclude' — pre-fills the per-quiz skip-scoring toggle on the Chat screen."""
    return get('last_skip_mode', 'zero')


def save_last_skip_mode(mode: str) -> None:
    set_value('last_skip_mode', mode)


def get_custom_api_url() -> str:
    return get('custom_api_url', '')


def get_custom_api_key() -> str:
    return get('custom_api_key', '')


def get_custom_model() -> str:
    return get('custom_model', '')


def save_custom_provider(url: str, key: str, model: str) -> None:
    update({'custom_api_url': url, 'custom_api_key': key, 'custom_model': model})


def get_provider_mode() -> str:
    mode = get('provider_mode', 'api')
    if mode == 'cli':
        return 'cli_bridge'
    return mode


def get_cli_model() -> str:
    return get('cli_model', 'opencode/big-pickle')


def save_provider_mode(mode: str) -> None:
    set_value('provider_mode', mode)


def save_cli_model(model: str) -> None:
    set_value('cli_model', model)


def get_agent_sessions() -> dict:
    """Returns {agent_name: session_id} for all agents."""
    return get('agent_sessions', {})


def save_agent_session(agent_name: str, session_id: str) -> None:
    """Save session ID for an agent."""
    sessions = get_agent_sessions()
    sessions[agent_name] = session_id
    set_value('agent_sessions', sessions)


def clear_agent_sessions() -> None:
    """Clear all agent sessions (new quiz session)."""
    set_value('agent_sessions', {})


def get_pending_messages() -> dict:
    """Returns {agent_name: [message_dict, ...]} for background models."""
    return get('pending_messages', {})


def save_pending_messages(agent_name: str, messages: list) -> None:
    """Save pending messages for an agent."""
    pending = get_pending_messages()
    pending[agent_name] = messages
    set_value('pending_messages', pending)


def clear_pending_messages() -> None:
    """Clear all pending messages."""
    set_value('pending_messages', {})


def get_question_count() -> int:
    """Returns the number of questions the student wants."""
    return get('question_count', 10)


def save_question_count(count: int) -> None:
    """Save the number of questions the student wants."""
    set_value('question_count', count)


def get_timer_settings() -> dict:
    """Returns the shared quiz timing preferences.

    Structure:
        timer_mode:  'off' | 'perQ' | 'total' — how (if at all) a countdown
                     is enforced
        timer_per_q: int — seconds allowed per question when mode is 'perQ'
        timer_total: int — minutes allowed for the whole quiz when mode is
                     'total'
        total_expiry: 'end' | 'continue' — what happens when the overall
                     time runs out
    """
    mode = get('timer_mode', 'off')
    if mode not in ('off', 'perQ', 'total'):
        mode = 'off'
    expiry = get('total_expiry', 'end')
    if expiry not in ('end', 'continue'):
        expiry = 'end'
    return {
        'timer_mode':  mode,
        'timer_per_q': int(get('timer_per_q', 60) or 60),
        'timer_total': int(get('timer_total', 10) or 10),
        'total_expiry': expiry,
    }


def save_timer_settings(
    timer_mode: str,
    timer_per_q: int,
    timer_total: int,
    total_expiry: str,
) -> None:
    """Persists the shared quiz timing preferences."""
    if timer_mode not in ('off', 'perQ', 'total'):
        timer_mode = 'off'
    if total_expiry not in ('end', 'continue'):
        total_expiry = 'end'
    update({
        'timer_mode':  timer_mode,
        'timer_per_q': max(1, int(timer_per_q)),
        'timer_total': max(1, int(timer_total)),
        'total_expiry': total_expiry,
    })


# ── Quota Manifest (Agent 1 output) ───────────────────────────────────────────

def save_quota_manifest(manifest: dict) -> None:
    """Save the quota manifest from Agent 1."""
    set_value('quota_manifest', manifest)


def get_quota_manifest() -> dict:
    """Returns the quota manifest from Agent 1, or empty dict."""
    return get('quota_manifest', {})


# ── Query Spec Manifest (Agent 2 output) ──────────────────────────────────────

def save_query_spec_manifest(manifest: dict) -> None:
    """Save the file query spec manifest from Agent 2."""
    set_value('query_spec_manifest', manifest)


def get_query_spec_manifest() -> dict:
    """Returns the file query spec manifest from Agent 2, or empty dict."""
    return get('query_spec_manifest', {})


# ── Selected Items Manifest (Agent 3 output) ──────────────────────────────────

def save_selected_items(manifest: dict) -> None:
    """Save the selected items manifest from Agent 3."""
    set_value('selected_items', manifest)


def get_selected_items() -> dict:
    """Returns the selected items manifest from Agent 3, or empty dict."""
    return get('selected_items', {})


# ── Sequenced Quiz Manifest (Agent 4 output) ──────────────────────────────────

def save_sequenced_quiz(manifest: dict) -> None:
    """Save the sequenced quiz manifest from Agent 4."""
    set_value('sequenced_quiz', manifest)


def get_sequenced_quiz() -> dict:
    """Returns the sequenced quiz manifest from Agent 4, or empty dict."""
    return get('sequenced_quiz', {})


# ── Compliance Audit Result (Agent 5 output) ─────────────────────────────────

def save_compliance_audit(result: dict) -> None:
    """Save the Agent 5 compliance audit result."""
    set_value('compliance_audit', result)


def get_compliance_audit() -> dict:
    """Returns the Agent 5 compliance audit result, or empty dict."""
    return get('compliance_audit', {})
