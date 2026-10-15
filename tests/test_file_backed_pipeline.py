"""Focused checks for file-backed CLI pipeline handoffs.

Runnable directly:  .venv/bin/python tests/test_file_backed_pipeline.py
(no pytest dependency).
"""

import ast
import contextlib
import json
import os
import sys
import tempfile
import threading
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from main_app import api_client, run_workspace
from main_app.api_client import CLIBridgeClient, _validate_command_size
from main_app.agent_runner import PROMPT_FILE_INSTRUCTION

AGENT_RUNNER = REPO / 'main_app' / 'agent_runner.py'


@contextlib.contextmanager
def env(**values):
    """Temporarily sets environment variables, restoring the old ones."""
    saved = {key: os.environ.get(key) for key in values}
    os.environ.update({k: v for k, v in values.items() if v is not None})
    try:
        yield
    finally:
        for key, old in saved.items():
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old


# ── Prompt-file handoff shape ─────────────────────────────────────────────────

def test_prompt_file_instruction_tells_agent_to_read_the_attachment():
    text = PROMPT_FILE_INSTRUCTION.lower()
    assert 'attached file' in text
    assert 'read' in text


def test_every_pipeline_call_attaches_exactly_one_file():
    """Guards against re-introducing the doubled payload (structured files
    *and* an instructions file) that pushed 3b from ~199 KB to ~491 KB."""
    tree = ast.parse(AGENT_RUNNER.read_text(encoding='utf-8'))
    offenders = []
    found = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (
            isinstance(func, ast.Attribute)
            and func.attr == 'call'
            and isinstance(func.value, ast.Attribute)
            and func.value.attr == '_client'
        ):
            continue
        files_kw = next((kw for kw in node.keywords if kw.arg == 'files'), None)
        if files_kw is None:
            continue
        found += 1
        attached = files_kw.value
        if not (isinstance(attached, ast.List) and len(attached.elts) == 1):
            detail = attached.elts if isinstance(attached, ast.List) else attached
            offenders.append((node.lineno, ast.dump(detail)[:120]))

    assert found == 9, f'expected 9 file-backed pipeline calls, found {found}'
    assert not offenders, (
        'each pipeline stage must attach exactly one prompt file; '
        f'offenders: {offenders}'
    )


# ── Workspace, argv guard, argv shape ────────────────────────────────────────

def test_workspace_writes_json_atomically():
    with tempfile.TemporaryDirectory() as home, env(QUIZ_APP_HOME=home):
        run = run_workspace.new_run({'question_count': 3})
        artifact = run_workspace.write(run, '04_candidates.json', {'1': [{'x': 1}]})
        assert artifact.is_file()
        assert artifact.is_relative_to(run)
        assert json.loads(artifact.read_text()) == {'1': [{'x': 1}]}
        assert json.loads((run / 'run.json').read_text())['question_count'] == 3


def test_argv_guard_rejects_single_oversized_argument():
    try:
        _validate_command_size(['opencode', 'run', 'x' * 131072], 'agent3b-candidate-selector')
    except OSError as exc:
        assert '131,072' in str(exc)
        assert '--file' in str(exc)
    else:
        raise AssertionError('oversized argument was accepted')


def test_agent_command_uses_absolute_repeatable_file_flags():
    captured = {}
    done = threading.Event()

    class Proc:
        returncode = 0

        def communicate(self, timeout=None):
            event = json.dumps({
                'type': 'text',
                'sessionID': 'ses_test',
                'part': {'type': 'text', 'sessionID': 'ses_test', 'text': 'ok'},
            })
            return event.encode(), b''

    def fake_popen(cmd, **kwargs):
        captured['cmd'] = cmd
        return Proc()

    client = CLIBridgeClient()
    with tempfile.TemporaryDirectory() as tmp:
        attachment = Path(tmp) / 'one.json'
        attachment.write_text('{}', encoding='utf-8')
        with mock.patch.object(client, 'is_configured', return_value=True), \
                mock.patch('main_app.api_client.subprocess.Popen', side_effect=fake_popen):
            client.call(
                agent='agent3b-candidate-selector',
                user='Read the attachment and return JSON.',
                files=[str(attachment)],
                on_success=lambda *_: done.set(),
                on_error=lambda error: (_ for _ in ()).throw(AssertionError(error)),
            )
            assert done.wait(2), 'CLI callback did not complete'

    cmd = captured['cmd']
    assert cmd[0:6] == ['opencode', 'run', '--format', 'json', '--agent', 'agent3b-candidate-selector']
    assert cmd[6:8] == ['--file', str(attachment)]
    assert cmd[-1] == 'Read the attachment and return JSON.'


# ── Payload guard (Fix 5) ─────────────────────────────────────────────────────

def test_payload_limit_defaults_to_300kb_and_honours_env():
    with env(QUIZ_APP_PAYLOAD_LIMIT_BYTES=None):
        assert api_client.payload_limit_bytes() == 300 * 1024
    with env(QUIZ_APP_PAYLOAD_LIMIT_BYTES='64000'):
        assert api_client.payload_limit_bytes() == 64000


def test_check_attachment_payload_warns_only_over_the_limit():
    with tempfile.TemporaryDirectory() as tmp, \
            env(QUIZ_APP_PAYLOAD_LIMIT_BYTES='1000'):
        small = Path(tmp) / 'small.txt'
        small.write_text('x' * 100, encoding='utf-8')
        big = Path(tmp) / 'big.txt'
        big.write_text('x' * 2000, encoding='utf-8')

        assert api_client.attachment_total_bytes([str(small)]) == 100
        assert api_client.attachment_total_bytes(['/no/such/file']) == 0
        assert api_client._check_attachment_payload([str(small)], 'agent-x') is None
        warning = api_client._check_attachment_payload([str(small), str(big)], 'agent-x')
        assert warning is not None
        assert 'agent-x' in warning
        assert '2,100' in warning


# ── Run retention (Fix 4) ─────────────────────────────────────────────────────

def test_run_retention_keeps_newest_and_protects_current():
    with tempfile.TemporaryDirectory() as home, \
            env(QUIZ_APP_HOME=home, QUIZ_APP_RUN_RETENTION='3'):
        made = [run_workspace.new_run({'n': i}) for i in range(5)]
        remaining = sorted(p.name for p in run_workspace.runs_root().iterdir())
        assert len(remaining) == 3
        assert made[-1].name in remaining          # the run just created survives
        assert made[0].name not in remaining       # the oldest was pruned


if __name__ == '__main__':
    test_prompt_file_instruction_tells_agent_to_read_the_attachment()
    test_every_pipeline_call_attaches_exactly_one_file()
    test_argv_guard_rejects_single_oversized_argument()
    test_agent_command_uses_absolute_repeatable_file_flags()
    test_payload_limit_defaults_to_300kb_and_honours_env()
    test_check_attachment_payload_warns_only_over_the_limit()
    test_run_retention_keeps_newest_and_protects_current()
    print('All file-backed pipeline tests passed.')
