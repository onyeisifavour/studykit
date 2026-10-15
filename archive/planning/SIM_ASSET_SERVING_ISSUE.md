# Issue: Simulations cannot load local assets — the sim endpoint serves HTML text only

**Status:** Closed — fixed 2026-10-01. See [Resolution](#resolution) at the end.
**Component:** `main_app/sidecar/app.py` (sim delivery), `main_app/sim_assets.py` + `main_app/sim_html.py` (new), `desktop/src/main/index.ts` (logging)
**Reported by:** orbital mechanics lab (`physics/Gravitational Fields and Orbital Mechanics/simulations/orbital_mechanics_lab`)
**Date:** 2026-10-01

---

## Summary

A simulation is delivered to the renderer as the **raw text of its `sim.html`** from a single endpoint. Any `<script src>`, `<link href>`, `<img src>` or CSS `url()` pointing at a sibling file inside the simulation folder resolves against that endpoint's URL and 404s.

The practical effect: **a simulation cannot reference any file of its own.** It must either reach the public internet for third-party libraries, or have every dependency inlined into its HTML. Neither is acceptable as the long-term arrangement.

---

## Root cause

The renderer loads each simulation in an iframe whose `src` is the sim endpoint:

`desktop/src/renderer/screens/Quiz.tsx:222`
```ts
q().simUrl = `${q().simBase}/api/sim/${encodeURIComponent(name)}`;
```

`desktop/src/renderer/screens/Quiz.tsx:1168-1171`
```tsx
<iframe ... src={q().simUrl} ... />
```

The sidecar resolves the folder, then returns only the one file's contents:

`main_app/sidecar/app.py:948-969`
```python
folder = candidates[0]
html = folder / 'sim.html'
if not html.exists():
    raise _SimLookupError(...)
return HTMLResponse(html.read_text(encoding='utf-8'), headers={...})
```

Two facts combine to produce the failure:

1. **There is no static file serving anywhere in the sidecar.** Every route was enumerated — the 47 handlers are all `/health`, `/api/quiz/*`, `/api/library/*`, `/api/settings`, `/api/sim/{sim_name}` and so on. There is no `StaticFiles` mount, no `/assets`, no file-serving handler of any kind.
2. **A relative URL in the document resolves against the document's own URL**, which is `/api/sim/{sim_name}` — not the filesystem path of `sim.html`.

So a script reference of `vendor/three.min.js` inside the document becomes a request for:

```
http://127.0.0.1:<port>/api/sim/vendor/three.min.js      →  404
```

and a "global" shared-assets reference of `../../../../vendor/three.min.js` becomes:

```
http://127.0.0.1:<port>/vendor/three.min.js              →  404
```

A filesystem-level static mount is not a drop-in alternative either, because the library root is user-configurable at runtime rather than fixed at process start:

`main_app/config.py:85`
```python
def get_library_root() -> str:
    return get('library_root', '')
```

The route can be served from `/api/sim/{sim_name}` but it cannot be *anchored* to the library directory at mount time.

---

## Reproduction

1. Place a simulation at `<library_root>/<subject>/<topic>/simulations/<sim_name>/sim.html`
2. Place `vendor/three.min.js` alongside it
3. Add `<script src="vendor/three.min.js"></script>` to `sim.html`
4. Run the quiz containing that simulation
5. Open the renderer devtools → Network, and the sim iframe's console

**Observed:** `GET /api/sim/vendor/three.min.js → 404`, then in the iframe console
`Uncaught ReferenceError: THREE is not defined`.

**Observed user-visible effect:** the simulation renders nothing at all. Because the physics and the renderer live in the same single `<script>` block, a failed library load aborts the entire IIFE — the WebGL canvas is never created, every readout stays on its `—` placeholder, the trajectory badge stays frozen on the value hardcoded in the markup, and Play/Reset do nothing. The controls still *look* interactive, which makes the failure easy to misdiagnose as a physics bug.

Note that serving the folder over a plain static file server (`python3 -m http.server`) works correctly. The failure is specific to the app's endpoint-based delivery, so it is not reproducible outside the app.

---

## Impact

- **Simulations require internet.** The only reliable library delivery today is a CDN URL, so the app cannot be used offline or on an isolated network — the normal case for a study/quiz tool.
- **No shared library cache.** The same 600 KB dependency must be duplicated into every simulation folder that needs it, or re-fetched per simulation from the network.
- **Silent, misleading failure mode.** A missing asset looks like a broken simulation rather than a missing file, and it takes down the simulation's logic as well as its visuals.
- **Blocks a reasonable storage layout.** A single shared `vendor/` directory at the library root — one copy of each third-party library, reused across all subjects — is not expressible today.

---

## Why inlining everything is not acceptable

Inlining the library into `sim.html` does work around the 404, and it is the current fallback. It should not be the resolution, because:

- **It defeats shared storage**, which is the entire goal. Every simulation that needs a 3D library would carry its own private 600 KB copy, and upgrading the library means editing every simulation file individually.
- **It is not a general answer.** Simulations legitimately need more than one script: worker files, WASM binaries, JSON or CSV data sets, shaders, textures, audio. Some of these are far too large to inline, and some cannot be inlined at all — a Web Worker or a `fetch()` of a data file cannot be expressed as an inline `<script>` tag in the parent document. An architecture that only supports inlining cannot host those simulations.
- **It makes every simulation file a generated artifact.** Every library bump rewrites every simulation, producing large, unreviewable diffs and making the authored source and the shipped file diverge.
- **It is a per-simulation workaround for a platform-level gap.** The defect is in how simulations are delivered, not in this one file.

---

## What the platform needs

Any one of the following would resolve the class of problem rather than this instance:

1. **Serve the simulation folder.** Add a handler that serves files under the resolved simulation folder, e.g. `GET /api/sim/{sim_name}/assets/{path:path}`, with path traversal rejected. Relative references in the document then resolve correctly, and the folder layout becomes expressible.
2. **Mount the library root.** Serve `<library_root>` as a static root so a single shared `vendor/` directory is reachable by every simulation in every subject. Requires resolving `library_root` per request (or re-mounting when the setting changes) rather than at import time.
3. **Rewrite asset URLs when serving.** Rewrite relative asset references in the returned HTML to absolute URLs pointing at whichever of the above is available. Preserves self-contained simulation sources on disk.

A shared `vendor/` directory at the library root is the preferred storage layout — one copy of each dependency, reused across all subjects — and options 1 and 2 both enable it.

---

## Acceptance criteria

- [ ] A simulation can load a script from a sibling file inside its own folder, with no internet access
- [ ] A simulation can load a shared library from a single library-root `vendor/` directory
- [ ] A second simulation in a different subject reuses that same shared copy without duplicating it
- [ ] Missing assets produce a clear, attributable error rather than a blank simulation
- [ ] Existing simulations that load their libraries from a CDN continue to work unchanged
- [ ] Simulations remain openable directly from disk (`file://`) for authoring and debugging

---

## Interim workaround currently in place

`sim.html` loads the vendored copy first and falls back to the CDN only if that fails, so the simulation works both standalone and inside the app:

```html
<script src="vendor/three.min.js"></script>
<script>window.THREE||document.write('<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"><\/script>')</script>
```

- Opened directly or served statically → the local copy is used, fully offline
- Inside the app → the local 404s and the CDN copy is used, so internet is still required

This is a stopgap. It keeps the app working today and keeps one canonical download at a single shared location, but the offline goal is only met once assets can be served properly.

---

## Notes for whoever picks this up

- `vendor/three.min.js` is currently stored **inside the simulation folder**. If a library-root `vendor/` is introduced, that file should move there and the sim's `src` should be repointed. Nothing else needs to change in the simulation.
- The canonical download is three.js **r128** (`vendor/three.min.js`, md5 `eb8549863a97355411c3259a3f93b8e1`). Note that the simulation's README previously claimed r152 — the README and the code disagreed; the code's r128 is correct.
- `library_scanner.py:130` (`_scan_simulations`) and the `_resolve_sim_html` docstring at `app.py:920` both establish the convention `<topic>/simulations/<sim_name>/sim.html`. Simulations are expected to live at a fixed depth below the library root, which a root-anchored mount could rely on.
- Google Fonts were also removed from this simulation's `<head>` for the same reason — webfonts cannot load offline. It now uses system font stacks. If webfonts are wanted, they need to be vendored and served, which requires the same fix.
---

## Resolution

All six acceptance criteria are met. Verified by `tests/test_sim_assets.py` (34 checks) and by
driving a real uvicorn server over HTTP against the live library, including a run with every
non-loopback socket blocked.

### What was added

| Piece | File | Role |
|---|---|---|
| Asset sandbox | `main_app/sidecar/app.py` → `GET /api/lib/{rel}` | Serves files inside a simulation folder and shared libraries from `X/vendor/`. Nothing else in the library is reachable. |
| Dependency cache | `main_app/sim_assets.py` | Downloads a CDN dependency once into `~/.quiz_app/sim_cache/`, serves it from disk forever after. |
| Cache endpoint | `main_app/sidecar/app.py` → `GET /api/sim-cache/{url}` | The local stand-in for a CDN URL. |
| HTML preparation | `main_app/sim_html.py` | Injects `<base href>` and rewrites allowlisted CDN URLs to the cache. Applied to the response only. |
| Console logging | `desktop/src/main/index.ts` | Forwards renderer and iframe console errors into `sidecar.log`. |

### Decisions worth knowing

**The `<base href>` mirrors the library's directory depth.** The sim's document is served from
`/api/sim/<name>`, whose base directory is only one level deep, so a relative path like
`../../../../vendor/x.js` would resolve to the server root and miss. The injected base is
`/api/lib/<subject>/<topic>/simulations/<sim_name>/`, which makes the browser resolve relative
paths to exactly where they resolve on disk. That is what keeps `file://` authoring working —
the same authored path is correct in both contexts.

**`/api/lib/` is deliberately narrower than the library root.** Serving the whole root would put
every `answer_bank.txt` and `concept_block.json` on an HTTP port. Only two locations are served:
a simulation's own folder, and `X/vendor/`. Tests assert the answer banks 403.

**Cache keys are URLs, not simulations.** 100+ simulations that all want three.js r128 share one
downloaded copy. Concurrent first-time loads of the same library fetch it once, under a per-URL
lock (test: 12 threads, 1 request).

**Revalidation is conditional and non-blocking.** Cached entries are re-checked with
`If-None-Match`/`If-Modified-Since` only after 24 hours, in a background task, so the canvas never
waits on the network. A fresh entry opens no socket at all. A failed revalidation keeps the cached
copy and logs the reason.

**The proxy is allowlisted and SSRF-guarded.** HTTPS only, host must be on a CDN allowlist, and
every resolved address is rejected if it lands on a private, loopback, link-local or reserved
range. Corrupt cache entries are detected by sha256 and dropped rather than served.

**The CDN fallback was removed.** The old `window.THREE||document.write(…)` stopgap was the reason
a missing library produced a blank canvas with nothing in any log: it worked online, failed
silently offline, and a network timeout is harder to diagnose than a 404. The sim now references
`../../../../vendor/three.min.js` and nothing else.

### Verified

- A sim's own sibling file, and `X/vendor/three.min.js`, both serve with correct content types.
- The browser-resolved URL returns bytes identical to `X/vendor/three.min.js` (603,445 bytes).
- `answer_bank.txt` → 403. Path traversal → 400. Missing file inside a sandbox → 404.
- A real CDN fetch of three.js r128 succeeded and its md5 matched the vendored copy; with the
  network patched to raise on any socket, the same URL was served from disk, byte-identical.
- A sim's file on disk is not modified — the base tag and URL rewrites exist only in the response.
- `sim.html` contains no CDN reference and no `document.write` fallback.

### Name collisions

`_resolve_sim_html` accepts either a bare folder name or a path relative to the library root
(`<topic>/simulations/<sim_name>`). A bare name still resolves when it is unique, and an ambiguous
name returns an error listing every candidate path rather than guessing. Passing the full path is
always unambiguous, so `question_generator` should emit it.

Bare module specifiers and `<script type="importmap">` are detected and logged as needing the
internet, rather than silently passed through. Full ES-module support (import maps) is not
implemented.
