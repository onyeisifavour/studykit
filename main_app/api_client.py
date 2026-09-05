"""
api_client.py

Multi-provider API client with automatic failover across GROQ and OpenRouter,
plus a CLI Bridge client that delegates to the opencode CLI.

THREAD SAFETY (TKINTER):
  on_success / on_error run on the background daemon thread.
  Wrap any UI-touching callback with root.after(0, ...):

      api.call(
          system=..., user=...,
          on_success=lambda t: root.after(0, lambda: handle(t)),
          on_error=lambda m: root.after(0, lambda: show_error(m)),
      )

Requires the 'requests' package:  pip install requests --break-system-packages
"""

import json
import os
import shutil
import sqlite3
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

import requests


GROQ_URL       = "https://api.groq.com/openai/v1/chat/completions"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

DEFAULT_GROQ_MODEL       = "llama-3.3-70b-versatile"
DEFAULT_OPENROUTER_MODEL = "meta-llama/llama-3.1-70b-instruct"
DEFAULT_CUSTOM_MODEL     = ""

_TIMEOUT_SECS = 60


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class Credential:
    provider: str   # 'groq' | 'openrouter' | 'custom'
    api_key:  str
    model:    str
    label:    str   # e.g. 'GROQ key 1' — used in failure reporting
    url:      str = ''  # only used for custom provider


@dataclass
class AttemptFailure:
    label:  str
    reason: str


# ── Client ────────────────────────────────────────────────────────────────────

class ApiClient:

    def __init__(
        self,
        groq_keys:        Optional[list[str]] = None,
        openrouter_keys:  Optional[list[str]] = None,
        groq_model:       Optional[str]       = None,
        openrouter_model: Optional[str]       = None,
        custom_url:       Optional[str]       = None,
        custom_key:       Optional[str]       = None,
        custom_model:     Optional[str]       = None,
    ):
        self._groq_keys        = list(groq_keys or [])
        self._openrouter_keys  = list(openrouter_keys or [])
        self._groq_model       = groq_model or DEFAULT_GROQ_MODEL
        self._openrouter_model = openrouter_model or DEFAULT_OPENROUTER_MODEL
        self._custom_url       = custom_url or ''
        self._custom_key       = custom_key or ''
        self._custom_model     = custom_model or DEFAULT_CUSTOM_MODEL

    # ── Configuration ─────────────────────────────────────────────────────────

    def configure(
        self,
        *,
        groq_keys:        Optional[list[str]] = None,
        openrouter_keys:  Optional[list[str]] = None,
        groq_model:       Optional[str]       = None,
        openrouter_model: Optional[str]       = None,
        custom_url:       Optional[str]       = None,
        custom_key:       Optional[str]       = None,
        custom_model:     Optional[str]       = None,
    ) -> None:
        """Updates credentials/models. Pass None to leave a value unchanged."""
        if groq_keys is not None:
            self._groq_keys = list(groq_keys)
        if openrouter_keys is not None:
            self._openrouter_keys = list(openrouter_keys)
        if groq_model:
            self._groq_model = groq_model
        if openrouter_model:
            self._openrouter_model = openrouter_model
        if custom_url is not None:
            self._custom_url = custom_url
        if custom_key is not None:
            self._custom_key = custom_key
        if custom_model is not None:
            self._custom_model = custom_model

    def is_configured(self) -> bool:
        return bool(self._credentials())

    def credential_count(self) -> int:
        return len(self._credentials())

    def _credentials(self) -> list[Credential]:
        creds: list[Credential] = []
        for i, key in enumerate(self._groq_keys, start=1):
            if key and key.strip():
                creds.append(Credential('groq', key.strip(), self._groq_model, f'GROQ key {i}'))
        for i, key in enumerate(self._openrouter_keys, start=1):
            if key and key.strip():
                creds.append(Credential('openrouter', key.strip(), self._openrouter_model, f'OpenRouter key {i}'))
        if self._custom_url and self._custom_key and self._custom_key.strip():
            creds.append(Credential('custom', self._custom_key.strip(), self._custom_model, 'Custom API', self._custom_url))
        return creds

    # ── Non-blocking call with failover ───────────────────────────────────────

    def call(
        self,
        *,
        system:     str,
        user:       str,
        history:    Optional[list[dict]]            = None,
        on_success: Optional[Callable[[str], None]] = None,
        on_error:   Optional[Callable[[str], None]] = None,
        max_tokens: int                              = 2000,
    ) -> None:
        """
        Makes an API call in a background daemon thread, trying each
        configured credential in order until one succeeds.

        on_success(response_text) — called once, on the first success.
        on_error(message)         — called ONLY if every credential fails;
                                     message lists the specific reason for
                                     each individual failure.
        """
        creds = self._credentials()
        if not creds:
            if on_error:
                on_error(
                    "No API keys configured. Add at least one GROQ, "
                    "OpenRouter, or Custom API key in Settings."
                )
            return

        messages = list(history) if history else []
        messages.append({'role': 'user', 'content': user})

        def _run() -> None:
            failures: list[AttemptFailure] = []

            for cred in creds:
                try:
                    text = _call_credential(cred, system, messages, max_tokens)
                    if on_success:
                        on_success(text)
                    return
                except Exception as exc:
                    failures.append(AttemptFailure(cred.label, _friendly_error(exc)))

            # Every credential failed — report exactly why each one did.
            if on_error:
                on_error(_format_all_failures(failures))

        threading.Thread(target=_run, daemon=True, name='api-client').start()


# ── Single-credential request ─────────────────────────────────────────────────

def _call_credential(
    cred:       Credential,
    system:     str,
    messages:   list[dict],
    max_tokens: int,
) -> str:
    if cred.provider == 'groq':
        url = GROQ_URL
        headers = {
            'Authorization': f'Bearer {cred.api_key}',
            'Content-Type':  'application/json',
        }
    elif cred.provider == 'custom':
        # Ensure URL ends with /chat/completions
        base = cred.url.rstrip('/')
        if not base.endswith('/chat/completions'):
            base += '/chat/completions'
        url = base
        headers = {
            'Authorization': f'Bearer {cred.api_key}',
            'Content-Type':  'application/json',
        }
    else:  # openrouter
        url = OPENROUTER_URL
        headers = {
            'Authorization': f'Bearer {cred.api_key}',
            'Content-Type':  'application/json',
            'HTTP-Referer':  'https://localhost',
            'X-Title':       'StudyKit Quiz App',
        }

    payload = {
        'model':      cred.model,
        'max_tokens': max_tokens,
        'messages':   [{'role': 'system', 'content': system}] + messages,
    }

    response = requests.post(url, headers=headers, json=payload, timeout=_TIMEOUT_SECS)

    if response.status_code == 401:
        raise PermissionError("invalid or expired API key")
    if response.status_code == 429:
        raise TimeoutError("rate limit reached")
    if response.status_code >= 500:
        raise ConnectionError(f"provider server error (HTTP {response.status_code})")
    if response.status_code != 200:
        raise RuntimeError(f"HTTP {response.status_code}: {response.text[:200]}")

    data = response.json()
    try:
        content = data['choices'][0]['message']['content']
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"unexpected response shape: {data}") from exc

    # Some OpenAI-compatible providers return "content": null on certain
    # finish reasons (content filtering, empty completions, tool-call-only
    # responses). Treat that as a failed attempt — NOT a successful None —
    # so the failover loop moves to the next credential instead of handing
    # None to a parser several stack frames away from any error handling.
    if not isinstance(content, str) or not content.strip():
        finish_reason = None
        try:
            finish_reason = data['choices'][0].get('finish_reason')
        except Exception:
            pass
        raise RuntimeError(f"empty or non-text response (finish_reason={finish_reason})")

    return content


# ── Error formatting ──────────────────────────────────────────────────────────

def _friendly_error(exc: Exception) -> str:
    if isinstance(exc, requests.exceptions.ConnectTimeout):
        return "connection timed out"
    if isinstance(exc, requests.exceptions.ConnectionError):
        return "could not connect (check your internet connection)"
    if isinstance(exc, (PermissionError, TimeoutError, ConnectionError)):
        return str(exc)
    return str(exc)


def _format_all_failures(failures: list[AttemptFailure]) -> str:
    """
    Builds the message shown to the user in the rare case that every
    configured credential fails. Each line names the exact credential
    and the exact reason, so the user knows precisely what to fix.
    """
    lines = [f"All {len(failures)} configured API key(s) failed:", ""]
    for f in failures:
        lines.append(f"  • {f.label} — {f.reason}")
    lines.append("")
    lines.append("Check your API keys in Settings, or try again in a moment.")
    return "\n".join(lines)


# ── CLI Bridge client ──────────────────────────────────────────────────────────

class CLIBridgeClient:
    """
    Delegates AI workloads to the 'opencode' CLI tool via subprocess.
    Same call() interface as ApiClient so the rest of the app doesn't
    know which backend is active.

    Requires 'opencode' to be installed and authenticated on the system.
    
    Supports:
    - Agent calls: use agent parameter to specify agent name
    - Session persistence: use session_id to continue a session
    - Returns (text, session_id) tuple via on_success
    """

    def __init__(self, model: str = 'opencode/big-pickle'):
        self._model = model

    def configure(self, *, model: Optional[str] = None, **_kwargs) -> None:
        if model:
            self._model = model

    def is_configured(self) -> bool:
        return shutil.which('opencode') is not None

    def call(
        self,
        *,
        agent:      Optional[str]                          = None,
        session_id: Optional[str]                          = None,
        system:     Optional[str]                          = None,
        user:       str,
        history:    Optional[list[dict]]                   = None,
        on_success: Optional[Callable[[str, str], None]]   = None,
        on_error:   Optional[Callable[[str], None]]        = None,
        max_tokens: int                                    = 2000,
    ) -> None:
        """
        Runs opencode in a background thread, capturing stdout/stderr.
        
        For agent calls:
        - agent: agent name (e.g., 'pre-quiz_main_chat')
        - session_id: session ID to continue (None for new session)
        - user: message to send (system prompt is built into agent)
        
        For legacy calls (no agent):
        - system: system prompt
        - user: user message
        
        on_success receives (response_text, session_id) tuple.
        """
        if not self.is_configured():
            if on_error:
                on_error(
                    "opencode CLI not found on this system. "
                    "Install it or switch to API mode in Settings."
                )
            return

        def _run() -> None:
            try:
                # Build command
                cmd = ['opencode', 'run', '--format', 'json']
                
                if agent:
                    cmd.extend(['--agent', agent])
                    if session_id:
                        cmd.extend(['-s', session_id])
                    # For agents, only send user message (system is built-in)
                    cmd.append(user)
                else:
                    # Legacy mode: combine system + user
                    if session_id:
                        cmd.extend(['-s', session_id])
                    full_prompt = f"{system}\n\n---\n\n{user}" if system else user
                    cmd.append(full_prompt)

                # Plain pipes (not a PTY): opencode only emits clean
                # --format json lines when stdout is not a TTY. stderr is
                # captured separately to avoid merging streams.
                last_error: Optional[str] = None
                for attempt in range(5):
                    if attempt:
                        time.sleep(3)
                    proc = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                    )
                    try:
                        out, err = proc.communicate(timeout=300)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
                        raise subprocess.TimeoutExpired(cmd, 300)

                    if proc.returncode != 0:
                        last_error = f"opencode exited with code {proc.returncode}"
                        continue

                    text, new_session_id = _extract_response_from_json(
                        (out + err).decode('utf-8', errors='replace')
                    )
                    if not text and new_session_id:
                        text = _read_session_text_from_db(new_session_id)
                    if text:
                        if on_success:
                            on_success(text, new_session_id or '')
                        return
                    last_error = "opencode returned empty response."

                if last_error:
                    if on_error:
                        on_error(last_error)

            except subprocess.TimeoutExpired:
                if on_error:
                    on_error("opencode timed out after 300 seconds.")
            except FileNotFoundError:
                if on_error:
                    on_error("opencode command not found. Is it installed?")
            except Exception as exc:
                if on_error:
                    on_error(f"CLI bridge error: {exc}")

        threading.Thread(target=_run, daemon=True, name='cli-bridge').start()


def _clean_student_reply(text: str) -> str:
    """
    Strips internal chain-of-thought / protocol analysis out of an assistant
    reply so the student only sees the conversational message.

    The cli-bridge model ("opencode/big-pickle") sometimes folds its reasoning
    into the same 'text' part as the real reply, either as a raw
    "monologue + reply" concatenation or wrapped in a
    '"Teacher message: ..." / "Student message: ..."' echo. Because opencode
    classifies that as text (not 'reasoning'), a type filter cannot remove it;
    we clean it here instead.

    Returns the cleaned reply, or the original string when no cleanup applies.
    """
    if not text:
        return text

    # 1) Strip "Teacher message:" / "Student message:" wrapper metadata.
    cleaned = text
    if 'Student message:' in cleaned:
        # The student echo marks the start/end of the wrapper; drop it and any
        # trailing echoed student input, keeping everything before "Student message:".
        cleaned = cleaned.split('Student message:', 1)[0]
    if cleaned.startswith('"Teacher message:'):
        cleaned = cleaned[len('"Teacher message:'):]
        cleaned = cleaned.rstrip().rstrip('"')
    cleaned = cleaned.strip()

    if not cleaned:
        return text

    # 2) Drop the internal-monologue preface, keeping the final student-facing
    #    reply. The analysis block is the trailing section written about the
    #    student in the third person / protocol terms; the actual reply is the
    #    last second-person conversational passage beginning after it.
    lines = [ln for ln in cleaned.splitlines() if ln.strip()]
    if len(lines) <= 1:
        return cleaned

    # Find the first line of the final conversational reply. Internal analysis
    # lines are those that describe the student or the plan ("The student ...",
    # "Per the protocol ...", "Let me ...", "This triggers Branch ...").
    internal_markers = (
        'the student', 'per the protocol', 'let me', 'this triggers',
        'this is strong', 'this shows', 'i have enough information',
        'looking at the digest', 'let me acknowledge', "i'll present",
        'i will', 'since the student', 'given the number',
    )

    # The reply is the last contiguous run of lines that do *not* look like
    # internal analysis. Walk backwards to find where the reply starts.
    reply_start = len(lines)
    for i in range(len(lines) - 1, -1, -1):
        line = lines[i].lstrip()
        low = line.lower()
        if any(low.startswith(m) for m in internal_markers):
            reply_start = i + 1
            break

    if reply_start < len(lines):
        reply = '\n'.join(lines[reply_start:]).strip()
        if reply:
            return reply

    return cleaned


def _read_session_text_from_db(session_id: str) -> str:
    """
    Fallback for when opencode's --format json stream emits events to stdout
    but the final assistant text part never makes it (known flakiness in the
    CLI bridge). The full response is still persisted in opencode's SQLite
    store, so we read the last text part for the session.

    Returns '' if nothing usable is found.
    """
    if not session_id:
        return ''
    try:
        base = os.environ.get(
            'XDG_DATA_HOME', os.path.expanduser('~/.local/share')
        )
        db_path = os.path.join(base, 'opencode', 'opencode.db')
        if not os.path.exists(db_path):
            return ''
        con = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True, timeout=5)
        try:
            rows = con.execute(
                'SELECT data FROM part WHERE session_id = ? '
                'ORDER BY time_created',
                (session_id,),
            ).fetchall()
        finally:
            con.close()
        texts: list[str] = []
        for (data,) in rows:
            try:
                part = json.loads(data)
            except (TypeError, ValueError):
                continue
            if isinstance(part, dict) and part.get('type') == 'text':
                t = part.get('text')
                if isinstance(t, str) and t.strip():
                    texts.append(t)
        return _clean_student_reply(texts[-1].strip()) if texts else ''
    except Exception:
        return ''


def _extract_response_from_json(stdout: str) -> tuple[str, str]:
    """
    Parses opencode's --format json output.
    Lines are JSON events; we look for the final assistant message text
    and the session ID.
    
    Returns (response_text, session_id).
    """
    text_parts: list[str] = []
    session_id: Optional[str] = None
    
    for line in stdout.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        if not isinstance(event, dict):
            continue

        # Extract session ID from first event that has it
        if session_id is None and 'sessionID' in event:
            session_id = event['sessionID']

        # opencode JSON events put text inside event['part']['text']
        part = event.get('part')
        if isinstance(part, dict) and part.get('type') == 'text':
            t = part.get('text', '')
            if t:
                text_parts.append(t)

        # Fallback: direct text field
        elif event.get('type') == 'text' and 'text' in event:
            text_parts.append(event['text'])

        # Assistant message content
        elif event.get('role') == 'assistant':
            content = event.get('content', '')
            if isinstance(content, str):
                text_parts.append(content)
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get('type') == 'text':
                        text_parts.append(block.get('text', ''))

    return _clean_student_reply('\n'.join(text_parts).strip()), session_id or ''
