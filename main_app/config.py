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
"""

import json
from pathlib import Path

_CONFIG_DIR  = Path.home() / '.quiz_app'
_CONFIG_FILE = _CONFIG_DIR / 'config.json'


def load() -> dict:
    """Loads and returns the full config dict. Returns {} if file missing/corrupt."""
    if _CONFIG_FILE.exists():
        try:
            return json.loads(_CONFIG_FILE.read_text(encoding='utf-8'))
        except Exception:
            return {}
    return {}


def save(data: dict) -> None:
    """Overwrites the config file with the given dict."""
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding='utf-8')


def get(key: str, default=None):
    """Gets a single value by key."""
    return load().get(key, default)


def set_value(key: str, value) -> None:
    """Sets a single key and persists."""
    cfg = load()
    cfg[key] = value
    save(cfg)


def update(updates: dict) -> None:
    """Merges multiple key-value pairs and persists."""
    cfg = load()
    cfg.update(updates)
    save(cfg)


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
