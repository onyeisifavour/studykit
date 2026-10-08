"""
sim_assets.py

On-disk cache for the third-party dependencies simulations pull from a CDN.

A simulation typically references its library with an absolute URL, e.g.
    <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js">
That works when the machine is online and fails silently when it is not: the
request stalls, the library never loads, and the simulation renders a blank
canvas with nothing in any log to explain it.

The sidecar rewrites those URLs to point at /api/sim-cache/<url> instead. The
bytes are downloaded once, stored under ~/.quiz_app/sim_cache/, and served from
disk on every later run — so a simulation only ever needs the internet the first
time it is opened. Because the cache is keyed by URL and not by simulation, the
100 simulations in the library that all want three.js r128 share one copy.

SECURITY: this module fetches a URL chosen by whoever authored the simulation.
Hosts are allowlisted, and every resolved address is rejected when it lands on
a private, loopback, link-local or reserved range, so a hostile or mistyped URL
cannot be used to reach services on the local network.
"""

import hashlib
import ipaddress
import json
import os
import re
import socket
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

CACHE_DIR = Path.home() / '.quiz_app' / 'sim_cache'

# Hosts whose assets we are willing to download and serve locally.
ALLOWED_HOSTS = frozenset({
    'cdnjs.cloudflare.com',
    'cdn.jsdelivr.net',
    'unpkg.com',
    'raw.githubusercontent.com',
    'github.com',
    'objects.githubusercontent.com',
    'esm.sh',
    'cdn.skypack.dev',
})

MAX_BYTES      = 25 * 1024 * 1024
TIMEOUT_SECS   = 10.0
# How long a cached entry is trusted before we quietly re-check it upstream.
REVALIDATE_AFTER = 24 * 60 * 60

_MIME = {
    '.js':    'text/javascript; charset=utf-8',
    '.mjs':   'text/javascript; charset=utf-8',
    '.cjs':   'text/javascript; charset=utf-8',
    '.map':   'application/json; charset=utf-8',
    '.json':  'application/json; charset=utf-8',
    '.css':   'text/css; charset=utf-8',
    '.html':  'text/html; charset=utf-8',
    '.wasm':  'application/wasm',
    '.png':   'image/png',
    '.jpg':   'image/jpeg',
    '.jpeg':  'image/jpeg',
    '.gif':   'image/gif',
    '.svg':   'image/svg+xml',
    '.webp':  'image/webp',
    '.ico':   'image/x-icon',
    '.hdr':   'image/vnd.radiance',
    '.glb':   'model/gltf-binary',
    '.gltf':  'model/gltf+json',
    '.bin':   'application/octet-stream',
    '.obj':   'text/plain; charset=utf-8',
    '.mtl':   'text/plain; charset=utf-8',
    '.ttf':   'font/ttf',
    '.otf':   'font/otf',
    '.woff':  'font/woff',
    '.woff2': 'font/woff2',
    '.mp3':   'audio/mpeg',
    '.ogg':   'audio/ogg',
    '.wav':   'audio/wav',
    '.mp4':   'video/mp4',
    '.ktx2':  'image/ktx2',
    '.basis': 'application/octet-stream',
}

_DEFAULT_MIME = 'application/octet-stream'

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


class SimAssetError(Exception):
    """Raised when an asset URL is rejected, or cannot be fetched and cached."""


def log(message: str) -> None:
    """Writes a timestamped line to stderr, which the Electron main process
    captures into sidecar.log. The repo does not otherwise use logging."""
    stamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    print(f'[{stamp}] sim-assets: {message}', file=sys.stderr, flush=True)


# ── URLs ──────────────────────────────────────────────────────────────────────

def is_allowed(url: str) -> bool:
    """True when the URL is a plain https URL on an allowlisted CDN host."""
    if not url or not url.lower().startswith('https://'):
        return False
    host = re.sub(r'^https://', '', url, flags=re.I).split('/', 1)[0].split('?', 1)[0]
    return host.split(':')[0].lower() in ALLOWED_HOSTS


def validate_url(url: str) -> str:
    """
    Normalises and vets a dependency URL.

    Raises SimAssetError when the URL is malformed, the host is not on the
    allowlist, or the host resolves to an address on the local network.
    """
    if not url or not url.lower().startswith('https://'):
        raise SimAssetError(f'refusing non-https asset URL: {url!r}')
    host = re.sub(r'^https://', '', url, flags=re.I).split('/', 1)[0].split('?', 1)[0]
    host = host.split(':')[0].lower()
    if host not in ALLOWED_HOSTS:
        raise SimAssetError(f'host {host!r} is not on the asset allowlist')

    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise SimAssetError(f'cannot resolve {host!r}: {exc}') from None

    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            raise SimAssetError(f'unparseable address for {host!r}: {addr!r}') from None
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            raise SimAssetError(
                f'{host!r} resolves to non-public address {addr}; refusing to fetch')
    return url


def content_type_for(url: str) -> str:
    """Picks a Content-Type from the URL's file extension."""
    path = re.sub(r'^https?://', '', url, flags=re.I).split('/', 1)[-1]
    path = path.split('?', 1)[0].split('#', 1)[0]
    return _MIME.get(Path(path).suffix.lower(), _DEFAULT_MIME)


def cache_key(url: str) -> str:
    """Stable filename-safe key for a URL."""
    return hashlib.sha256(url.encode('utf-8')).hexdigest()


# ── Storage ───────────────────────────────────────────────────────────────────

def _body_path(url: str) -> Path:
    return CACHE_DIR / f'{cache_key(url)}.bin'


def _meta_path(url: str) -> Path:
    return CACHE_DIR / f'{cache_key(url)}.json'


@contextmanager
def _url_lock(url: str):
    """Serialises work on one URL so many simulations loading at once fetch a
    given library exactly once instead of racing each other."""
    with _locks_guard:
        lock = _locks.setdefault(cache_key(url), threading.Lock())
    with lock:
        yield


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _write_atomic(path: Path, data: bytes) -> None:
    """Writes via a temp file and renames, so a crash or quit mid-write can
    never leave a truncated file in the cache."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f'.tmp{os.getpid()}')
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def store(url: str, body: bytes, headers: dict | None = None) -> dict:
    """Persists a downloaded body plus its metadata. Returns the metadata."""
    if len(body) > MAX_BYTES:
        raise SimAssetError(
            f'asset is {len(body)} bytes, over the {MAX_BYTES} byte limit: {url}')
    headers = headers or {}
    meta = {
        'url':          url,
        'content_type': content_type_for(url),
        'bytes':        len(body),
        'sha256':       hashlib.sha256(body).hexdigest(),
        'etag':         headers.get('etag') or headers.get('ETag') or '',
        'last_modified': headers.get('last-modified') or headers.get('Last-Modified') or '',
        'fetched_at':   _now(),
        'checked_at':   _now(),
    }
    _write_atomic(_body_path(url), body)
    _write_atomic(_meta_path(url), json.dumps(meta, indent=2).encode('utf-8'))
    return meta


def read_meta(url: str) -> dict:
    path = _meta_path(url)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return {}


def read_cached(url: str) -> tuple[bytes, dict] | None:
    """Returns (body, meta) for a cached URL, or None when it is not cached."""
    body_path, meta_path = _body_path(url), _meta_path(url)
    if not body_path.exists() or not meta_path.exists():
        return None
    try:
        body = body_path.read_bytes()
        meta = json.loads(meta_path.read_text(encoding='utf-8'))
    except Exception as exc:
        log(f'cache read failed for {url}: {exc}')
        return None
    if meta.get('sha256') and hashlib.sha256(body).hexdigest() != meta['sha256']:
        log(f'cache entry for {url} is corrupt (sha256 mismatch); discarding')
        body_path.unlink(missing_ok=True)
        meta_path.unlink(missing_ok=True)
        return None
    return body, meta


# ── Network ───────────────────────────────────────────────────────────────────

def _http_get(url: str, headers: dict | None = None):
    """Seam around requests so tests can substitute a fake transport."""
    import requests
    return requests.get(url, headers=headers or {}, timeout=TIMEOUT_SECS,
                        stream=True, allow_redirects=True)


def _read_capped(resp) -> bytes:
    """Reads at most MAX_BYTES so a hostile or runaway response cannot fill
    the disk."""
    chunks, total = [], 0
    for chunk in resp.iter_content(64 * 1024):
        if not chunk:
            continue
        total += len(chunk)
        if total > MAX_BYTES:
            raise SimAssetError(f'asset exceeds the {MAX_BYTES} byte limit')
        chunks.append(chunk)
    return b''.join(chunks)


def fetch(url: str) -> tuple[bytes, dict]:
    """
    Downloads a dependency and stores it. Raises SimAssetError on any failure.

    Sends conditional headers when a cached copy exists so an unchanged file
    costs a 304 rather than a full download.
    """
    validate_url(url)
    headers: dict[str, str] = {}
    prior = read_meta(url)
    if prior.get('etag'):
        headers['If-None-Match'] = prior['etag']
    if prior.get('last_modified'):
        headers['If-Modified-Since'] = prior['last_modified']

    try:
        resp = _http_get(url, headers)
    except Exception as exc:
        raise SimAssetError(f'network error fetching {url}: {exc}') from None

    with resp:
        if resp.status_code == 304 and prior:
            prior['checked_at'] = _now()
            _write_atomic(_meta_path(url), json.dumps(prior, indent=2).encode('utf-8'))
            return b'', prior
        if resp.status_code >= 400:
            raise SimAssetError(f'{url} returned HTTP {resp.status_code}')
        body = _read_capped(resp)
        meta = store(url, body, dict(resp.headers))
    return body, meta


def refresh(url: str) -> bool:
    """
    Quietly re-checks a cached entry. Never raises, and never overwrites a good
    copy with a failure — the whole point is that an offline run keeps working.
    """
    try:
        validate_url(url)
    except SimAssetError as exc:
        log(f'revalidation refused: {exc}')
        return False
    try:
        _, meta = fetch(url)
    except SimAssetError as exc:
        log(f'revalidation failed, keeping cached copy: {exc}')
        return False
    log(f'revalidated {url} ({meta.get("bytes", 0)} bytes)')
    return True


def maybe_revalidate(url: str) -> bool:
    """
    Re-checks a cached entry only when it has actually gone stale.

    This is what the sidecar runs after serving bytes. Keeping the staleness
    test here means a fresh entry costs no DNS lookup and no socket at all —
    which is the whole point, since 100+ simulations loading offline must not
    each wait on a connection timeout.
    """
    if not _is_stale(read_meta(url)):
        return False
    return refresh(url)


def get(url: str) -> tuple[bytes, dict]:
    """
    Main entry point: returns the bytes for a dependency URL, from disk when
    possible and from the network only on the first run.

    Raises SimAssetError when the URL is not fetchable and not cached.
    """
    with _url_lock(url):
        hit = read_cached(url)
        if hit is not None:
            body, meta = hit
            if _is_stale(meta):
                threading.Thread(target=refresh, args=(url,), daemon=True).start()
            return body, meta
        try:
            return fetch(url)
        except SimAssetError as exc:
            log(f'NOT CACHED and could not be downloaded: {exc}')
            raise


def _is_stale(meta: dict) -> bool:
    try:
        checked = datetime.fromisoformat(meta.get('checked_at') or meta.get('fetched_at') or '')
    except (TypeError, ValueError):
        return True
    return (time.time() - checked.timestamp()) > REVALIDATE_AFTER


def clear() -> int:
    """Empties the cache. Returns the number of entries removed."""
    if not CACHE_DIR.exists():
        return 0
    removed = 0
    for body in CACHE_DIR.glob('*.bin'):
        body.unlink(missing_ok=True)
        body.with_suffix('.json').unlink(missing_ok=True)
        removed += 1
    return removed


def stats() -> dict:
    """Human-readable cache summary, for Settings and for log lines."""
    if not CACHE_DIR.exists():
        return {'entries': 0, 'bytes': 0, 'cache_dir': str(CACHE_DIR)}
    entries, total = 0, 0
    for meta_path in sorted(CACHE_DIR.glob('*.json')):
        try:
            meta = json.loads(meta_path.read_text(encoding='utf-8'))
        except Exception:
            continue
        entries += 1
        total += int(meta.get('bytes') or 0)
    return {
        'entries': entries,
        'bytes': total,
        'cache_dir': str(CACHE_DIR),
        'urls': [json.loads(p.read_text(encoding='utf-8')).get('url', '')
                 for p in sorted(CACHE_DIR.glob('*.json'))
                 if p.exists()],
    }
