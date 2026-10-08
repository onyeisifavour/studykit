# Orbital Mechanics — Newton's Law of Gravitation

## Overview

An interactive 3D simulation of orbital mechanics based on Newton's Law of Universal Gravitation. Students explore how initial conditions (distance, velocity, mass) affect orbital trajectories, learning to distinguish circular, elliptical, parabolic-threshold, hyperbolic-escape and radial/collision trajectories.

## Physics Model

**Scope: a test particle in the external field of one fixed, spherically symmetric central body.** This is a deliberately simple Newtonian model, and the simulator tells the student when a run leaves its assumptions.

- **Gravity:** a = μ/r², μ = GM, directed at the central body. Valid only for r ≥ R (outside the body).
- **Central body:** fixed at the origin, with a physical radius R = R☉·(M/M☉)^0.8 (approximate main-sequence scaling; 0.0047 AU for 1 M☉). The body is drawn at true radius (never smaller than a minimum visible size); a red ring always marks the true contact radius R used by the physics.
- **Contact:** the integrator tests every step for contact (r ≤ R) and stops at first contact. There is no interior model, so a collision is never continued through the body and never mistaken for an escape.
- **Integration:** Velocity Verlet with a single adaptive timestep controller used for *all* trajectory classes (see below).
- **Constants:** G = 6.674 × 10⁻¹¹ m³/(kg·s²), 1 AU = 1.496 × 10¹¹ m.

### Reference equations

| Quantity | Equation |
|---|---|
| Gravitational parameter | μ = GM |
| Specific orbital energy | ε = v²/2 − μ/r |
| Specific angular momentum | h = \|r × v\| |
| Eccentricity | e = √(1 + 2εh²/μ²) |
| Semi-major axis (ε < 0) | a = −μ/(2ε) |
| Periapsis | r_p = (h²/μ)/(1 + e) |
| Circular speed | v_circ = √(μ/r) |
| Escape speed | v_esc = √(2μ/r) |
| Closed-orbit period | T = 2π√(a³/μ), only for a valid bound ellipse |

### Trajectory classification

Classification uses energy first, then angular momentum, then collision state. Eccentricity is displayed but is never the test for bound versus escape.

| State | Condition |
|---|---|
| Collision / entered central body | Body reached r = R (integration stopped) |
| Radial bound / collision | h ≈ 0 and ε < 0 |
| Radial plunge (unbound) / collision | h ≈ 0, ε ≥ 0, moving inward |
| Radial escape | h ≈ 0, ε ≥ 0, moving outward |
| Parabolic threshold | \|ε\| ≈ 0 (within 0.4 % of μ/r₀ at launch) |
| Circular | ε < 0, e < 0.02 |
| Elliptical | ε < 0, e ≥ 0.02 |
| Hyperbolic escape | ε > 0 (e > 1) |

Tolerances are numerical, never exact equality: radial means \|h\|/(r·v) < 10⁻³, and the threshold energy is compared with μ/r at *launch*, so the class cannot change along a run (ε is conserved). A bound orbit whose periapsis lies inside R is still "Elliptical", but the UI warns that it will collide and the run stops at the surface.

### Timestep controller

One controller, used for bound, unbound and radial motion, depends only on the local state: dt = η · min(r/v, √(r³/μ)) with η = 0.002. That limits the fractional change per step in radius (Δr ≤ η·r), velocity (Δv ≤ η·v_circ) and orbital phase. On an inbound leg a step also never covers more than half the remaining gap to the surface, and every step is checked for contact along its chord, so a step cannot jump across the body. At most 8000 substeps are taken per rendered frame; if that is not enough, playback slows ("Slowed: resolving periapsis") rather than switching to a coarser step.

### Model-validity warnings

- **Mass ratio:** a warning appears when m/M > 0.01. The model holds the central body fixed and ignores its recoil, so periods are off by roughly 50·(m/M) %.
- **Speed:** a warning appears when v exceeds 10 % of c, and a stronger one at v ≥ c. Newtonian kinetic energy and orbital formulas are not valid there.
- **Contact:** the model has no stellar interior; a collision stops the run.

Thresholds live in the `MODEL` object at the top of the physics core.

## Parameters (Controls)

| Parameter | Label | Range | Default | Unit | Description |
|-----------|-------|-------|---------|------|-------------|
| `distance` | Distance | 0.5 – 5.0 | 1.5 | AU | Initial distance from central body |
| `velocity` | Velocity magnitude | 5 – 80 | 25 | km/s | Initial speed of orbiting body |
| `direction` | Velocity direction | 0 – 360 | 90 | ° | Direction of initial velocity (0° = radial outward, 90° = tangential) |
| `mass_central` | Central mass | 0.1 – 5.0 | 1.0 | M☉ | Mass of central body (solar masses); also sets R |
| `mass_orbit` | Orbiting mass | 0.0001 – 0.1 | 0.001 | M☉ | Mass of orbiting body; treated as negligible, with a warning when m/M > 0.01 |
| `sim_speed` | Simulation speed | 0.1 – 10.0 | 1.0 | × | Time multiplier for simulation |

## Controls

| Control | Action |
|---------|--------|
| Play/Pause button | Toggle simulation running/paused — pauses in place. After a collision it reads "Collided" and is disabled until End |
| End button | Stop the run and return the orbiting body to its launch point (clears the trail), keeping the current parameters |
| Reset button | Stop the run and restore all parameters to defaults (view/camera untouched) |
| Sliders | Adjust parameters in real-time (changing a launch parameter while stopped re-derives the launch point) |
| Mouse drag | Rotate 3D view (orbit camera) |
| Mouse wheel | Zoom in/out |
| `Space` | Play/pause (keyboard) |
| `R` | Reset parameters to defaults (keyboard) |
| `?` | Toggle keyboard help overlay |
| `+` / `-` | Increase/decrease font size |
| `Esc` | Close any open overlay |

## Outputs (Readouts)

| Output | Unit | Description |
|--------|------|-------------|
| `trajectory` | — | State badge (see classification table) |
| notes | — | Model-validity, collision-course and contact messages |
| `distance` | AU | Current distance from central body |
| `force` | N | Gravitational force magnitude |
| `speed` | km/s | Current speed |
| `period` | yr | Finite only for a valid closed bound orbit; otherwise "No closed period" |
| `eccentricity` | — | Orbital parameter (shown as "(radial)" when h ≈ 0); not used for classification |
| `semiMajorAxis` | AU | a = −μ/(2ε) for ε < 0 on a closed orbit; "∞ (parabolic)", "n/a (open orbit)" or "n/a (radial)" otherwise |
| `periapsis` | AU | r_p, compared against R to predict collisions |
| `bodyRadius` | AU | Central body radius R used for contact |
| `escapeVelocity` | km/s | √(2μ/r) at the current distance |
| `specificEnergy`, `angularMomentum` | J/kg, m²/s | ε and h, the quantities classification is based on |
| `kineticEnergy`, `potentialEnergy` | J | Energy of the orbiting body |
| Numerical diagnostics | — | Closest approach reached, energy drift \|Δε\|/(largest energy scale reached), current timestep, playback state |

## Visualization

- **Central body:** Golden sphere at true radius (minimum visible size), with a red ring at the true contact radius R
- **Orbiting body:** Blue sphere
- **Force vector:** Red arrow with cone arrowhead
- **Velocity vector:** Blue arrow with cone arrowhead
- **Orbital trail:** Color-coded by speed (blue=slow, green=medium, red=fast); sampled by distance travelled so periapsis stays smooth
- **Distance marker:** Dashed line between bodies
- **Predicted ellipse:** Faint analytic overlay for closed bound orbits
- **Reference plane:** Translucent disc in orbital plane

## Instructional Phases

### Phase 1: Exploration
- Explore the simulation freely
- Adjust controls and observe effects
- Goal: Set up a circular orbit

### Phase 2: Guided Discovery
- Predict orbital parameters before running
- Verify predictions against simulation
- Goal: Understand distance-period relationship

### Phase 3: Challenge
- Achieve specific eccentricity targets
- Create nearly circular, moderately eccentric, and escape orbits
- Goal: Control orbital parameters precisely

### Phase 4: Mastery
- Demonstrate understanding through assessment
- Explain orbital mechanics principles
- Goal: Articulate key concepts

## Adaptive Pathways

The pathway tag counts distinct trajectory types demonstrated (circular, elliptical, escape; parabolic, hyperbolic and radial-escape all count as escape). Collisions and radial plunges do not count. Three types gives "Accelerated pace".

## Validation

`physics_tests.js` loads the physics core directly from `sim.html` and runs the brief's validation cases: circular orbit, moderate ellipse, parabolic threshold, hyperbolic escape, radial bound plunge, high-eccentricity periapsis inside the body, near-surface periapsis, mass-ratio and speed guards, timestep behaviour, and class invariance along a run.

```
node physics_tests.js sim.html
```

## Accessibility

- Full keyboard navigation
- ARIA labels on all interactive elements
- Screen reader announcements for state changes (including collision)
- Adjustable font size

## Technical Implementation

- **Rendering:** Three.js (WebGL)
- **Physics:** Custom Velocity Verlet integrator with adaptive timestep (pure-function core, delimited by `PHYSICS CORE BEGIN/END` markers in `sim.html`)
- **Audio:** None (visual simulation)
- **Storage:** None (sandboxed, no localStorage)
- **External dependencies:** Three.js r128, loaded from the shared library folder at `X/vendor/three.min.js`. It is referenced as `../../../../vendor/three.min.js` — four levels up from this folder is the library root, because the scanner places every simulation at `<subject>/<topic>/simulations/<sim_name>/`.
- **Network:** Fully offline. No CDN, webfont, or remote requests; fonts fall back to system stacks.
- **Output:** a single `sim.html`. All shared libraries live in `X/vendor/`, not in this folder.

### Referencing libraries from a new simulation

Either of these work, and both behave identically whether the sim is opened from
disk or served by the app:

- **A shared library already in `X/vendor/`** — reference it relatively as
  `../../../../vendor/<file>`. One copy serves every simulation in the library.
- **A library reached by URL** — write the normal absolute CDN URL in a
  `<script src>` or a module `import`. The app downloads it once, stores it under
  `~/.quiz_app/sim_cache/`, and serves it from disk on every later run, so the
  simulation only needs the internet the first time it is opened. Nothing in the
  sim file needs editing.

Bare module specifiers (`import … from 'three'`) and `<script type="importmap">`
are **not** cached — they need the internet every time. Use an absolute URL or a
path under `X/vendor/` instead.

## Out of scope

Multiple gravitating bodies, N-body dynamics, barycentric motion, perturbations and body spawning are intentionally not part of this model.

## Browser Compatibility

- Chrome/Edge 90+
- Firefox 88+
- Safari 14+

Requires WebGL support.
