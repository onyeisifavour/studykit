"""
sim_html.py

Prepares a simulation's sim.html for delivery through the sidecar.

A sim is written to be opened straight off disk, so it references its library
by absolute CDN URL. Served over HTTP that same URL means the browser reaches
out to the internet on every load and stalls when there is none. Two changes
are applied to the response only — the file on disk is never rewritten:

  1. A <base href> is injected so relative paths resolve to the same place
     whether the sim is served by the app or opened from file://.
  2. Allowlisted CDN URLs are rewritten to the local cache, so after the first
     run the simulation never touches the network again.

Patterns we cannot cache (bare module specifiers, import maps) are reported
rather than silently passed through, so a simulation that still needs the
internet says so instead of rendering a blank canvas.
"""

import re

from . import sim_assets

# <script src="…">, <link href="…">, <img src="…"> and friends.
_ATTR_URL_RE = re.compile(
    r'''(?P<attr>\b(?:src|href)\s*=\s*)(?P<q>["'])(?P<url>https://[^"']+)(?P=q)''',
    re.IGNORECASE,
)

# Absolute URLs inside inline module code: import … from 'https://…'
# and dynamic import('https://…').
_JS_URL_RE = re.compile(
    r'''(?P<q>['"])(?P<url>https://[^'"]+)(?P=q)'''
)

# Patterns the cache cannot satisfy on its own.
_IMPORTMAP_RE = re.compile(r'<script[^>]*type\s*=\s*["\']importmap["\']', re.IGNORECASE)
_BARE_IMPORT_RE = re.compile(
    r'''(?:\bfrom|\bimport)\s*\(?\s*(?P<q>['"])(?P<spec>[^.'"][^'"]*)(?P=q)''')


def cache_url_for(url: str) -> str:
    """The sidecar path that serves a dependency from the local cache."""
    return '/api/sim-cache/' + url


def base_href_for(rel_folder: str) -> str:
    """A <base href> that mirrors the sim's depth inside the library.

    Scans always place a sim at <subject>/<topic>/simulations/<sim_name>/, so a
    sim written as ../../vendor/x.js reaches X/vendor/ whether it is served here
    or opened from disk.
    """
    rel = rel_folder.strip('/')
    return f'/api/lib/{rel}/' if rel else '/api/lib/'


def _replace_urls(text: str, seen: set) -> tuple[str, list[str]]:
    """Rewrites allowlisted absolute URLs to cache URLs. Returns (text, skipped)."""
    skipped: list[str] = []

    def _sub_attr(m: re.Match) -> str:
        url = m.group('url')
        if not sim_assets.is_allowed(url):
            skipped.append(url)
            return m.group(0)
        seen.add(url)
        return f'{m.group("attr")}{m.group("q")}{cache_url_for(url)}{m.group("q")}'

    def _sub_js(m: re.Match) -> str:
        url = m.group('url')
        if not sim_assets.is_allowed(url):
            return m.group(0)
        seen.add(url)
        return f'{m.group("q")}{cache_url_for(url)}{m.group("q")}'

    text = _ATTR_URL_RE.sub(_sub_attr, text)
    text = _JS_URL_RE.sub(_sub_js, text)
    return text, skipped


def _find_unsupported(text: str) -> list[str]:
    """Names the caching patterns present in the sim that will not work offline."""
    problems: list[str] = []
    if _IMPORTMAP_RE.search(text):
        problems.append('uses <script type="importmap"> (bare specifiers need internet)')
    for m in _BARE_IMPORT_RE.finditer(text):
        spec = m.group('spec')
        if spec.startswith(('.', '/')) or re.match(r'^[a-z][a-z0-9+.-]*:', spec, re.I):
            continue
        problems.append(f'bare module specifier {spec!r} (needs internet)')
    # De-duplicate, keep order.
    seen, out = set(), []
    for p in problems:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _inject_base(html: str, base: str) -> str:
    """Adds <base href> to <head> unless the sim already declares one."""
    if re.search(r'<base\s', html, re.IGNORECASE):
        sim_assets.log('sim declares its own <base>; leaving it alone')
        return html
    tag = f'<base href="{base}">'
    m = re.search(r'<head[^>]*>', html, re.IGNORECASE)
    if m:
        return html[:m.end()] + '\n' + tag + html[m.end():]
    return tag + '\n' + html


def prepare(html: str, base: str) -> tuple[str, list[str]]:
    """
    Returns (html_to_serve, notes) for a simulation.

    notes lists anything the student should know about offline behaviour —
    unsupported patterns, and external URLs that were left pointing at the
    internet because their host is not on the allowlist.
    """
    unsupported = _find_unsupported(html)
    for problem in unsupported:
        sim_assets.log(f'UNSUPPORTED for offline caching: {problem}')

    seen: set = set()
    rewritten, skipped = _replace_urls(html, seen)
    for url in sorted(seen):
        sim_assets.log(f'cacheable dependency: {url}')
    for url in sorted(set(skipped) - seen):
        sim_assets.log(f'external URL left as-is (host not allowlisted): {url}')

    notes = list(unsupported)
    if seen:
        notes.append(f'{len(seen)} dependenc'
                     f'{"y" if len(seen) == 1 else "ies"} redirected to the local cache')
    return _inject_base(rewritten, base), notes
