# Projectile Motion Lab

An offline-first, sandbox-safe, single-page projectile-motion simulator over
level ground. Enter a launch angle and a launch velocity, fire, and watch the
closed-form trajectory draw itself while live flight values update (max height,
range, flight time). No network, no storage, no external resources — the whole
lab ships as one self-contained `sim.html` and runs inside an
`<iframe sandbox="allow-scripts">`.

Physics is the classic no-drag ballistic model with launch height `h0 = 0` and
gravity `g = 9.8 m/s²`:

| Quantity | Formula |
| --- | --- |
| Flight time | `T = 2·v0·sin(θ) / g` |
| Max height | `H = v0²·sin²(θ) / (2·g)` |
| Range | `R = v0²·sin(2·θ) / g` |

Golden values (also asserted by the kinematics tests):

| v0 (m/s) | θ (deg) | H (m) | R (m) | T (s) |
| --- | --- | --- | --- | --- |
| 20 | 45 | 10.2 | 40.8 | 2.9 |
| 20 | 30 | 5.1 | 35.4 | 2.0 |
| 20 | 60 | 15.3 | 35.4 | 3.5 |
| 25 | 45 | 15.9 | 63.8 | 3.6 |

Degenerate angles are handled without `NaN` or division blow-ups: θ = 0° gives
`T = H = R = 0`, θ = 90° gives `R = 0`.

## Usage

Run from `projectile-lab/`:

```
npm install
npx vite build          # build the app bundle (dist/)
npx vite build --config vite.sim.config.ts   # single-chunk build (dist-sim/)
```

Open `sim.html` (workspace root) directly in a browser, or embed it:

```html
<iframe src="sim.html" sandbox="allow-scripts"></iframe>
```

Controls:

- **Launch angle** — range 0–90°, step 1°, default 45°
- **Velocity** — range 5–40 m/s, step 0.5, default 20 m/s
- **Fire** — launch the projectile with the current parameters
- **Reset** — restore defaults and clear output/canvas

Readouts (one decimal): **Max height** (m), **Range** (m), **Flight time** (s).

## `window.__sim` contract

The lab exposes a stable bridge for sandbox hosts. The shell owns the boundary:
the app never reads `window.__sim`; the bridge only touches
`data-sim-param` / `data-sim-output` / `data-sim-action` elements and window
CustomEvents (`sim:run`, `sim:reset`).

```js
window.__sim = {
  params: {
    launch_angle: { label: "Launch angle", type: "range", min: 0, max: 90, step: 1, default: 45, unit: "\u00b0" },
    velocity:     { label: "Velocity", type: "range", min: 5, max: 40, step: 0.5, default: 20, unit: "m/s" },
    reset:        { type: "button", label: "Reset" }
  },
  reset()          { /* restore default params; dispatch "sim:reset" */ },
  run(state)       { /* apply (clamped) state, e.g. {launch_angle, velocity}; dispatch "sim:run" */ },
  onParamsChanged(cb) { /* cb({launch_angle, velocity}) on user input; returns unsubscribe */ },
  getOutputs()     { /* { maxHeight, range, flightTime } — 1-decimal numbers */ },
  getState()       { /* { launch_angle, velocity, maxHeight, range, flightTime } */ },
  metadata: {
    name: "projectile_motion",
    topic: "L1.5 Two-Dimensional Projectile Trajectories and Fluid Resistance",
    outputs: ["maxHeight", "range", "flightTime"]
  }
};
```

`run()` clamps the launch angle to [0, 90] and the velocity to [5, 40].

## Verification

Checklist used to validate this deliverable (see the project report):

1. `npx vite build` produces `dist/` (and `dist-sim/` for the single-chunk inline build).
2. `sim.html` is fully self-contained: no `<script src=`, no `fetch(`, no
   `XMLHttpRequest`, no `http(s)://` anywhere in the file.
3. `window.__sim` and the `data-sim-param` / `data-sim-output` contract
   attributes are present.
4. `shell_validator.py` passes all checks.
5. No placeholder tokens (`TODO` / `FIXME` / `XXX` / `Not implemented` / `stub`
   / `lorem`) in any produced source or deliverable.

## Notes for maintainers

- `vite.sim.config.ts` mirrors `vite.config.ts` with `manualChunks` disabled so
  the produced bundle is a single inlineable module. Rebuild it whenever the
  app changes, then regenerate `sim.html`.
- The `@tailwindcss/vite` plugin is intentionally not enabled: v4.0.0 crashes
  under the pinned Node toolchain on any CSS transform. Styles are plain token
  CSS in `src/ui/styles/theme.css`.
- Vite's modulepreload polyfill is disabled in both build profiles
  (`modulePreload: false`) — the inline build must not emit `fetch()`.