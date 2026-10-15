"""Config durability: atomic writes, backup recovery, profile-key retention.

Regression cover for the data-loss bug that dropped every user setting (and
could equally have dropped the learner-profile pointers) while the app was
running: `save()` used a non-atomic `write_text`, and `load()` returned `{}`
for any parse error, so a read that landed mid-write wiped the file.

Run: python tests/test_config_durability.py
"""

import json
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_TMP = Path(tempfile.mkdtemp(prefix='quiz-config-test-'))
os.environ['HOME'] = str(_TMP)
os.environ['XDG_CONFIG_HOME'] = str(_TMP / '.config')

for _m in [m for m in list(sys.modules) if m.startswith('main_app')]:
    del sys.modules[_m]

from main_app import config

PASS, FAIL = 0, 0


def check(label, cond, extra=''):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f'PASS {label}')
    else:
        FAIL += 1
        print(f'FAIL {label} {extra}')


def test_profile_keys_survive_concurrent_writes():
    config.save({})
    config.update({
        'library_root': '/lib',
        'selected_topics': ['/lib/maths/L1.1'],
        'current_quiz_id': 'abc123',
        'agent_sessions': {'knowledge-graph-builder': 'ses_k'},
        'pending_messages': {'knowledge-graph-builder': [{'m': 1}]},
    })

    def worker(i):
        for _ in range(40):
            config.set_value(f'run_key_{i}', i)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    data = config.load()
    check('agent_sessions retained under concurrent writes',
          data.get('agent_sessions') == {'knowledge-graph-builder': 'ses_k'},
          data.get('agent_sessions'))
    check('pending_messages retained under concurrent writes',
          data.get('pending_messages') == {'knowledge-graph-builder': [{'m': 1}]})
    check('current_quiz_id retained', data.get('current_quiz_id') == 'abc123')
    check('user settings retained',
          data.get('selected_topics') == ['/lib/maths/L1.1']
          and data.get('library_root') == '/lib')
    check('every concurrent write landed',
          all(f'run_key_{i}' in data for i in range(8)))


def test_corrupt_live_file_recovers_from_backup():
    config.save({})
    config.update({
        'selected_topics': ['/lib/maths/L1.1'],
        'agent_sessions': {'drill-recommender': 'ses_d'},
    })
    # Simulate a torn / half-written file.
    config._CONFIG_FILE.write_text('{"selected_topics": ["/lib/maths/L1.1"', encoding='utf-8')

    data = config.load()
    check('corrupt config does not silently become {}',
          data.get('agent_sessions') == {'drill-recommender': 'ses_d'}, data)
    check('broken bytes quarantined for inspection',
          len(list(config._CONFIG_DIR.glob('config.corrupt-*.json'))) >= 1)
    check('live file reseeded with valid JSON',
          isinstance(json.loads(config._CONFIG_FILE.read_text(encoding='utf-8')), dict))


def test_readers_never_see_torn_json():
    config.save({'seed': 0})
    stop = threading.Event()
    seen_bad = []

    def writer():
        i = 0
        while not stop.is_set():
            config.set_value('blob', 'x' * 5000 + str(i))
            i += 1

    def reader():
        while not stop.is_set():
            try:
                json.loads(config._CONFIG_FILE.read_text(encoding='utf-8'))
            except FileNotFoundError:
                pass
            except Exception as exc:
                seen_bad.append(repr(exc))

    threads = [threading.Thread(target=writer)]
    threads += [threading.Thread(target=reader) for _ in range(3)]
    for t in threads:
        t.start()
    time.sleep(0.5)
    stop.set()
    for t in threads:
        t.join()

    check('readers never observe torn JSON during concurrent writes',
          not seen_bad, seen_bad[:1])


def run():
    test_profile_keys_survive_concurrent_writes()
    test_corrupt_live_file_recovers_from_backup()
    test_readers_never_see_torn_json()
    print(f'\n{PASS} passed, {FAIL} failed')
    shutil.rmtree(_TMP, ignore_errors=True)
    return FAIL


if __name__ == '__main__':
    sys.exit(1 if run() else 0)
