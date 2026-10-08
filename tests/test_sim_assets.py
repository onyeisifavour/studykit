"""Inline tests for simulation asset serving: the dependency cache, the
/api/lib/ sandbox, and the HTML rewriting applied to sim.html.

Run: .venv/bin/python tests/test_sim_assets.py
"""
import sys
import os
import socket
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main_app import sim_assets
from main_app import sim_html
from main_app.sidecar import app as sidecar
from fastapi.testclient import TestClient

print('PASS 0: module import')

CDN = 'https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js'

# ── 1. URL allowlist ───────────────────────────────────────────────────────────

assert sim_assets.is_allowed(CDN)
assert sim_assets.is_allowed('https://unpkg.com/three@0.160/build/three.module.js')
assert not sim_assets.is_allowed('http://cdnjs.cloudflare.com/ajax/libs/x.js')  # http
assert not sim_assets.is_allowed('https://evil.example.com/x.js')
assert not sim_assets.is_allowed('https://cdnjs.cloudflare.com.evil.com/x.js')
assert not sim_assets.is_allowed('')
print('PASS 1: allowlist accepts CDNs, rejects everything else')

for bad in ('http://cdnjs.cloudflare.com/a.js', 'https://evil.example.com/a.js',
            'ftp://unpkg.com/a.js', 'https://localhost/a.js', ''):
    try:
        sim_assets.validate_url(bad)
        raise AssertionError(f'should have been rejected: {bad}')
    except sim_assets.SimAssetError:
        pass
print('PASS 2: validate_url refuses non-allowlisted and non-https URLs')

# ── 3. SSRF guard: an allowlisted-looking host resolving to a private IP ───────

_real_getaddrinfo = socket.getaddrinfo
def _fake_getaddrinfo(host, port, *a, **k):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', port))]

socket.getaddrinfo = _fake_getaddrinfo
try:
    sim_assets.validate_url(CDN)
    raise AssertionError('should have refused a loopback resolution')
except sim_assets.SimAssetError as exc:
    assert 'non-public' in str(exc), exc
finally:
    socket.getaddrinfo = _real_getaddrinfo
print('PASS 3: host resolving to loopback is refused (SSRF guard)')

def _fake_private(host, port, *a, **k):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('169.254.169.254', port))]

socket.getaddrinfo = _fake_private
try:
    sim_assets.validate_url(CDN)
    raise AssertionError('should have refused link-local (cloud metadata)')
except sim_assets.SimAssetError:
    pass
finally:
    socket.getaddrinfo = _real_getaddrinfo
print('PASS 4: link-local address (cloud metadata) is refused')

# ── 5. Content types ───────────────────────────────────────────────────────────

assert sim_assets.content_type_for(CDN) == 'text/javascript; charset=utf-8'
assert sim_assets.content_type_for('https://unpkg.com/a/b.mjs') == 'text/javascript; charset=utf-8'
assert sim_assets.content_type_for('https://unpkg.com/a/b.wasm') == 'application/wasm'
assert sim_assets.content_type_for('https://unpkg.com/a/b.glb') == 'model/gltf-binary'
assert sim_assets.content_type_for('https://unpkg.com/a/b.css') == 'text/css; charset=utf-8'
assert sim_assets.content_type_for('https://unpkg.com/a/b.unknownext') == 'application/octet-stream'
# Query strings must not confuse extension detection.
assert sim_assets.content_type_for('https://unpkg.com/a/three.min.js?v=1') \
       == 'text/javascript; charset=utf-8'
print('PASS 5: content types, including query strings')

assert sim_assets.cache_key(CDN) == sim_assets.cache_key(CDN)
assert sim_assets.cache_key(CDN) != sim_assets.cache_key('https://unpkg.com/x.js')
assert len(sim_assets.cache_key(CDN)) == 64
print('PASS 6: cache keys are stable and unique')

# ── 7. Store / read / corrupt / clear ─────────────────────────────────────────

with tempfile.TemporaryDirectory() as tmp:
    sim_assets.CACHE_DIR = Path(tmp) / 'sim_cache'

    body = b'/* three.js */ console.log(1);'
    meta = sim_assets.store(CDN, body, {'ETag': 'W/"abc"', 'Last-Modified': 'Mon, 01 Jan 2024 00:00:00 GMT'})
    assert meta['bytes'] == len(body)
    assert meta['sha256'] and meta['etag'] == 'W/"abc"'

    hit = sim_assets.read_cached(CDN)
    assert hit is not None and hit[0] == body
    assert sim_assets.read_cached('https://unpkg.com/missing.js') is None
    print('PASS 7: store then read_cached round-trips')

    # A corrupted body must be discarded, not served.
    sim_assets._body_path(CDN).write_bytes(b'tampered')
    assert sim_assets.read_cached(CDN) is None
    assert not sim_assets._body_path(CDN).exists()
    print('PASS 8: corrupt cache entry is detected via sha256 and dropped')

    # Oversized assets are refused.
    sim_assets.MAX_BYTES = 8
    try:
        sim_assets.store('https://unpkg.com/big.js', b'x' * 100)
        raise AssertionError('should have refused an oversized asset')
    except sim_assets.SimAssetError as exc:
        assert 'limit' in str(exc)
    sim_assets.MAX_BYTES = 25 * 1024 * 1024
    print('PASS 9: oversized asset refused')

    sim_assets.store(CDN, body)
    sim_assets.store('https://unpkg.com/x.js', b'var x=1;')
    s = sim_assets.stats()
    assert s['entries'] == 2, s
    assert s['bytes'] == len(body) + 8
    assert sim_assets.clear() == 2
    assert sim_assets.stats()['entries'] == 0
    print('PASS 10: stats and clear')

# ── 11. Fetch uses conditional headers; 304 keeps the body ─────────────────────

class _Resp:
    def __init__(self, status, body=b'', headers=None):
        self.status_code, self._body, self.headers = status, body, headers or {}
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def iter_content(self, n):
        for i in range(0, len(self._body), n):
            yield self._body[i:i+n]

with tempfile.TemporaryDirectory() as tmp:
    sim_assets.CACHE_DIR = Path(tmp) / 'sim_cache'
    sim_assets.store(CDN, b'old', {'ETag': 'W/"v1"'})

    seen = {}
    def _ok(url, headers=None):
        seen.update(headers or {})
        return _Resp(200, b'new', {'ETag': 'W/"v2"'})
    sim_assets._http_get = _ok
    b, m = sim_assets.fetch(CDN)
    assert b == b'new' and m['etag'] == 'W/"v2"'
    assert seen.get('If-None-Match') == 'W/"v1"', seen
    print('PASS 11: fetch sends If-None-Match from the cached copy')

    def _304(url, headers=None):
        return _Resp(304)
    sim_assets._http_get = _304
    b, m = sim_assets.fetch(CDN)
    assert b == b'' and sim_assets.read_cached(CDN)[0] == b'new'
    print('PASS 12: 304 revalidation keeps the cached body')

    # HTTP errors and network errors both become SimAssetError.
    sim_assets._http_get = lambda url, headers=None: _Resp(404)
    try:
        sim_assets.fetch(CDN)
        raise AssertionError('should have raised on HTTP 404')
    except sim_assets.SimAssetError as exc:
        assert '404' in str(exc)

    def _boom(url, headers=None):
        raise OSError('network unreachable')
    sim_assets._http_get = _boom
    try:
        sim_assets.fetch('https://unpkg.com/never-cached.js')
        raise AssertionError('should have raised on network error')
    except sim_assets.SimAssetError:
        pass
    print('PASS 13: HTTP and network failures raise SimAssetError')

# ── 14. get() serves from cache without any network call ──────────────────────

with tempfile.TemporaryDirectory() as tmp:
    sim_assets.CACHE_DIR = Path(tmp) / 'sim_cache'
    sim_assets.store(CDN, b'cached bytes')

    def _must_not_call(url, headers=None):
        raise AssertionError('get() touched the network for a cached URL')
    sim_assets._http_get = _must_not_call

    b, m = sim_assets.get(CDN)
    assert b == b'cached bytes'
    print('PASS 14: get() returns cached bytes with no network access (offline-safe)')

    # A fresh entry must not trigger a revalidation thread.
    sim_assets._http_get = _must_not_call
    sim_assets.get(CDN)

    # An entry older than REVALIDATE_AFTER is revalidated, off the request path.
    import json as _json
    meta_path = sim_assets._meta_path(CDN)
    m2 = _json.loads(meta_path.read_text())
    m2['checked_at'] = '2000-01-01T00:00:00+00:00'
    meta_path.write_text(_json.dumps(m2))
    assert sim_assets._is_stale(m2) is True
    assert sim_assets._is_stale({'checked_at': '2999-01-01T00:00:00+00:00'}) is False
    # maybe_revalidate is what the route calls; a fresh entry must not dial out.
    sim_assets.store(CDN, b'cached bytes')
    assert sim_assets.maybe_revalidate(CDN) is False, 'fresh entry was revalidated'
    # A stale one does go to the network, and a failure there is not fatal.
    sim_assets._body_path(CDN).unlink()
    sim_assets._meta_path(CDN).unlink()
    sim_assets.store(CDN, b'cached bytes')
    _m = __import__('json').loads(sim_assets._meta_path(CDN).read_text())
    _m['checked_at'] = '2000-01-01T00:00:00+00:00'
    sim_assets._meta_path(CDN).write_text(__import__('json').dumps(_m))
    assert sim_assets.maybe_revalidate(CDN) is False, 'should report failure, not raise'
    assert sim_assets.read_cached(CDN)[0] == b'cached bytes', 'stale copy must survive'
    print('PASS 15: staleness drives revalidation, fresh entries stay local')

# ── 16. Concurrency: many sims want three.js at once, fetch once ──────────────

with tempfile.TemporaryDirectory() as tmp:
    sim_assets.CACHE_DIR = Path(tmp) / 'sim_cache'
    sim_assets._locks.clear()
    calls = []
    call_lock = threading.Lock()
    def _counting(url, headers=None):
        with call_lock:
            calls.append(url)
        threading.Event().wait(0.05)  # widen the race window
        return _Resp(200, b'three', {'ETag': 'W/"t"'})
    sim_assets._http_get = _counting
    socket.getaddrinfo = lambda host, port, *a, **k: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', port))]
    try:
        results = []
        def _worker():
            try:
                results.append(sim_assets.get(CDN)[0])
            except Exception as exc:
                results.append(exc)
        threads = [threading.Thread(target=_worker) for _ in range(12)]
        for t in threads: t.start()
        for t in threads: t.join()
    finally:
        socket.getaddrinfo = _real_getaddrinfo

    assert results == [b'three'] * 12, results
    assert len(calls) == 1, f'expected 1 fetch for 12 concurrent sims, got {len(calls)}'
    print('PASS 16: 12 concurrent sims trigger exactly 1 download (shared by URL)')

def _run_sandbox_checks(sim_dir: Path, client):
    r = client.get('/api/lib/vendor/three.min.js')
    assert r.status_code == 200 and r.content == b'THREE-LIB', r.status_code
    assert r.headers['content-type'].startswith('text/javascript')
    print('PASS 20: X/vendor/three.min.js is served with a JS content type')

    r = client.get('/api/lib/physics/Topic/simulations/s1/data.json')
    assert r.status_code == 200 and r.json() == {'a': 1}
    r = client.get('/api/lib/physics/Topic/simulations/s1/sub/deeper.js')
    assert r.status_code == 200 and r.text == 'deep'
    print('PASS 21: files inside a simulation folder are served')

    for secret in ('/api/lib/answer_bank.txt',
                   '/api/lib/physics/Topic/answer_bank.txt',
                   '/api/lib/physics/Topic/concept_block.json'):
        r = client.get(secret)
        assert r.status_code in (403, 404), f'{secret} returned {r.status_code}'
        assert 'SECRET' not in r.text
    print('PASS 22: answer banks and concept blocks are NOT served')

    for escape in ('/api/lib/../../../etc/passwd',
                   '/api/lib/vendor/../../../etc/passwd',
                   '/api/lib/physics/Topic/simulations/s1/../../../answer_bank.txt'):
        r = client.get(escape)
        assert r.status_code in (400, 403, 404), f'{escape} returned {r.status_code}'
    print('PASS 23: path traversal is refused')

    assert client.get('/api/lib/physics/Topic/notes.txt').status_code == 403
    assert client.get('/api/lib/nope.txt').status_code == 403
    assert client.get('/api/lib/physics/Topic/simulations/s1/missing.js').status_code == 404
    print('PASS 24: outside-sandbox paths 403, missing files in-sandbox 404')

    (sim_dir / 'sim.html').write_text(
        '<html><head><title>s</title></head><body>'
        f'<script src="{CDN}"></script>'
        '<script src="../../../../vendor/three.min.js"></script>'
        '</body></html>')

    r = client.get('/api/sim/s1')
    assert r.status_code == 200, r.text
    body = r.text
    assert '<base href="/api/lib/physics/Topic/simulations/s1/">' in body
    assert '/api/sim-cache/' + CDN in body, 'CDN URL was not redirected to the cache'
    assert '../../../../vendor/three.min.js' in body
    print('PASS 25: /api/sim injects base and redirects the CDN to the cache')

    on_disk = (sim_dir / 'sim.html').read_text()
    assert '<base' not in on_disk, 'the sim file on disk was modified'
    assert CDN in on_disk, 'the original CDN URL in the sim file was rewritten on disk'
    print('PASS 26: the sim file on disk is left byte-for-byte alone')


# ── 17. HTML rewriting ─────────────────────────────────────────────────────────

html = (
    '<html><head><title>t</title></head><body>\n'
    f'<script src="{CDN}"></script>\n'
    '<script type="module">\n'
    '  import { OrbitControls } from "https://cdn.jsdelivr.net/npm/three@0.160/examples/jsm/controls/OrbitControls.js";\n'
    "  import local from './local.js';\n"
    "  import shared from '../shared/thing.js';\n"
    '</script>\n'
    '<img src="https://example.com/not-allowed.png">\n'
    '</body></html>'
)
served, notes = sim_html.prepare(html, '/api/lib/physics/T/simulations/s1/')

assert f'<base href="/api/lib/physics/T/simulations/s1/">' in served
assert '/api/sim-cache/' + CDN in served
assert '/api/sim-cache/https://cdn.jsdelivr.net/npm/three@0.160' in served
assert './local.js' in served and '../shared/thing.js' in served
assert 'https://example.com/not-allowed.png' in served, 'non-allowlisted URL must be left alone'
assert '/api/sim-cache//api/sim-cache' not in served, 'double rewrite'
assert CDN not in served.replace('/api/sim-cache/' + CDN, ''), 'original CDN URL still present'
print('PASS 17: CDN URLs rewritten, local paths untouched, base injected once')

# An existing <base> is respected rather than duplicated.
served2, _ = sim_html.prepare('<html><head><base href="/custom/"></head></html>', '/api/lib/x/')
assert served2.count('<base') == 1 and '/custom/' in served2
print('PASS 18: a sim that declares its own <base> keeps it')

# Unsupported patterns are reported, not silently ignored.
import_map = ('<html><head><script type="importmap">'
              '{"imports":{"three":"/vendor/three.module.js"}}</script></head></html>')
_, notes = sim_html.prepare(import_map, '/api/lib/x/')
assert any('importmap' in n for n in notes), notes

bare = "<html><head><script type='module'>import * as THREE from 'three';</script></head></html>"
_, notes = sim_html.prepare(bare, '/api/lib/x/')
assert any('bare module specifier' in n for n in notes), notes
# A relative specifier is not "bare" and must not be reported.
ok = "<html><head><script type='module'>import x from './y.js';</script></head></html>"
_, notes = sim_html.prepare(ok, '/api/lib/x/')
assert not notes, notes
print('PASS 19: importmap and bare specifiers are flagged for the log')

# ── 20. /api/lib sandbox: sim files and X/vendor, nothing else ─────────────────

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp) / 'X'
    sim_dir = root / 'physics' / 'Topic' / 'simulations' / 's1'
    sim_dir.mkdir(parents=True)
    (root / 'vendor').mkdir()
    (root / 'vendor' / 'three.min.js').write_bytes(b'THREE-LIB')
    (sim_dir / 'sim.html').write_text('<html></html>')
    (sim_dir / 'data.json').write_text('{"a":1}')
    (sim_dir / 'sub').mkdir()
    (sim_dir / 'sub' / 'deeper.js').write_text('deep')
    # Things that must never be servable.
    (root / 'answer_bank.txt').write_text('SECRET ANSWERS')
    topic = root / 'physics' / 'Topic'
    (topic / 'answer_bank.txt').write_text('SECRET ANSWERS')
    (topic / 'concept_block.json').write_text('SECRET CONCEPT')

    real_saved = sidecar.config.get('library_root', None)
    try:
        sidecar.config.save_library_root(str(root))
        client = TestClient(sidecar.app)
        _run_sandbox_checks(sim_dir, client)
    finally:
        # Tests must never leave the app pointed at a deleted temp directory.
        if real_saved:
            sidecar.config.save_library_root(real_saved)
        else:
            sidecar.config.update({'library_root': ''})
    assert sidecar.config.get_library_root() != str(root), 'test leaked library_root'
    print('PASS 27b: the real library_root setting is restored after the test')


# ── 27. Cache route: serves from cache, refuses non-https ─────────────────────

with tempfile.TemporaryDirectory() as tmp:
    sim_assets.CACHE_DIR = Path(tmp) / 'sim_cache'
    sim_assets.store(CDN, b'cached three')
    client = TestClient(sidecar.app)

    r = client.get('/api/sim-cache/' + CDN)
    assert r.status_code == 200 and r.content == b'cached three', r.status_code
    assert r.headers['content-type'].startswith('text/javascript')
    print('PASS 27: /api/sim-cache serves a cached dependency with the right type')

    assert client.get('/api/sim-cache/http://unpkg.com/x.js').status_code == 400
    print('PASS 28: /api/sim-cache refuses non-https keys')

    # An uncached URL that cannot be downloaded is a 502 with an actionable message.
    def _fail(url, headers=None):
        raise OSError('no route to host')
    sim_assets._http_get = _fail
    socket.getaddrinfo = lambda host, port, *a, **k: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', port))]
    try:
        r = client.get('/api/sim-cache/https://unpkg.com/not-cached.js')
    finally:
        socket.getaddrinfo = _real_getaddrinfo
    assert r.status_code == 502, r.status_code
    assert 'while online' in r.json()['detail'], r.json()
    print('PASS 29: uncached+undownloadable gives an actionable 502')

    # A host that is not allowlisted never reaches the network.
    r = client.get('/api/sim-cache/https://evil.example.com/x.js')
    assert r.status_code == 502 and 'allowlist' in r.json()['detail']
    print('PASS 30: non-allowlisted host is rejected by the cache route')

# ── 31. Cache diagnostics endpoints ────────────────────────────────────────────

with tempfile.TemporaryDirectory() as tmp:
    sim_assets.CACHE_DIR = Path(tmp) / 'sim_cache'
    sim_assets.store(CDN, b'12345')
    client = TestClient(sidecar.app)
    s = client.get('/api/sim-cache-stats').json()
    assert s['entries'] == 1 and s['bytes'] == 5
    assert CDN in s['urls']
    assert client.delete('/api/sim-cache').json()['removed'] == 1
    assert client.get('/api/sim-cache-stats').json()['entries'] == 0
    print('PASS 31: cache stats and clear endpoints work')


# ── 32. Sim lookup: unique bare names, path disambiguation, collisions ─────────

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp) / 'X'
    for subject, topic, sim in [('physics', 'Orbital',  'pendulum_lab'),
                                ('maths',   'Algebra',  'pendulum_lab'),
                                ('physics', 'Orbital',  'orbital_lab')]:
        d = root / subject / topic / 'simulations' / sim
        d.mkdir(parents=True)
        (d / 'sim.html').write_text('<html></html>')

    real_saved = sidecar.config.get('library_root', None)
    try:
        sidecar.config.save_library_root(str(root))
        lookup = sidecar._resolve_sim_html

        def _rel(ref):
            return lookup(ref)[0].as_posix().split('X/')[-1]

        # A unique bare name must keep working: existing questions store just the folder name.
        assert _rel('orbital_lab') == 'physics/Orbital/simulations/orbital_lab'
        # A path pins one exact folder, so two subjects can both have pendulum_lab.
        assert _rel('physics/Orbital/simulations/pendulum_lab') == 'physics/Orbital/simulations/pendulum_lab'
        assert _rel('maths/Algebra/simulations/pendulum_lab') == 'maths/Algebra/simulations/pendulum_lab'
        # Matching is case-insensitive and tolerates a trailing slash.
        assert _rel('PHYSICS/Orbital/Simulations/Pendulum_Lab') == 'physics/Orbital/simulations/pendulum_lab'
        assert _rel('physics/Orbital/simulations/orbital_lab/') == 'physics/Orbital/simulations/orbital_lab'
        print('PASS 32: bare names still resolve; paths disambiguate colliding sims')

        # A collision must name the paths that work, not just refuse.
        for ref in ('pendulum_lab', 'Orbital/simulations/pendulum_lab'):
            try:
                lookup(ref)
                raise AssertionError(f'{ref!r} should be reported as ambiguous')
            except sidecar._SimLookupError as exc:
                assert 'physics/Orbital' in str(exc) and 'maths/Algebra' in str(exc), str(exc)
        print('PASS 33: an ambiguous name lists every candidate path')

        for bad in ('nope_lab', 'physics/Nope/simulations/x', 'nowhere/entirely', ''):
            try:
                lookup(bad)
                raise AssertionError(f'should have raised for {bad!r}')
            except sidecar._SimLookupError:
                pass
        print('PASS 34: unknown and empty names still fail cleanly')
    finally:
        if real_saved:
            sidecar.config.save_library_root(real_saved)
        else:
            sidecar.config.update({'library_root': ''})

print('\nAll sim asset and lookup tests passed.')
