# Orbital Mechanics — Newton's Law of Gravitation

## Overview

An interactive 3D simulation of orbital mechanics based on Newton's Law of Universal Gravitation. Students explore how initial conditions (distance, velocity, mass) affect orbital trajectories, learning to distinguish between circular, elliptical, and escape trajectories.

## Physics Model

- **Gravitational force:** F = G × M × m / r²
- **Integration:** Velocity Verlet (symplectic, energy-conserving)
- **Timestep:** Fixed 1/120 s with frame-rate accumulator
- **Constants:** G = 6.674 × 10⁻¹¹ m³/(kg·s²), 1 AU = 1.496 × 10¹¹ m

## Parameters (Controls)

| Parameter | Label | Range | Default | Unit | Description |
|-----------|-------|-------|---------|------|-------------|
| `distance` | Distance | 0.5 – 5.0 | 1.5 | AU | Initial distance from central body |
| `velocity` | Velocity magnitude | 5 – 80 | 25 | km/s | Initial speed of orbiting body |
| `direction` | Velocity direction | 0 – 360 | 90 | ° | Direction of initial velocity (0° = radial outward, 90° = tangential) |
| `mass_central` | Central mass | 0.1 – 5.0 | 1.0 | M☉ | Mass of central body (solar masses) |
| `mass_orbit` | Orbiting mass | 0.0001 – 0.1 | 0.001 | M☉ | Mass of orbiting body (solar masses) |
| `sim_speed` | Simulation speed | 0.1 – 10.0 | 1.0 | × | Time multiplier for simulation |

## Controls

| Control | Action |
|---------|--------|
| Play/Pause button | Toggle simulation running/paused |
| Reset button | Restore all parameters to defaults |
| Sliders | Adjust parameters in real-time |
| Mouse drag | Rotate 3D view (orbit camera) |
| Mouse wheel | Zoom in/out |
| `Space` | Play/pause (keyboard) |
| `R` | Reset simulation (keyboard) |
| `?` | Toggle keyboard help overlay |
| `+` / `-` | Increase/decrease font size |
| `Esc` | Close any open overlay |

## Outputs (Readouts)

| Output | Unit | Description |
|--------|------|-------------|
| `distance` | AU | Current distance from central body |
| `force` | N | Gravitational force magnitude |
| `speed` | km/s | Current orbital speed |
| `period` | s | Orbital period (∞ for escape trajectories) |
| `eccentricity` | — | Orbital eccentricity (0 = circular, ≥1 = escape) |
| `semiMajorAxis` | AU | Semi-major axis (∞ for escape trajectories) |
| `trajectory` | — | Classification: Circular / Elliptical / Escape |
| `kineticEnergy` | J | Kinetic energy of orbiting body |
| `potentialEnergy` | J | Gravitational potential energy |
| `escapeVelocity` | m/s | Escape velocity at current distance |

## Visualization

- **Central body:** Golden sphere (star/planet)
- **Orbiting body:** Blue sphere
- **Force vector:** Red arrow with cone arrowhead, labeled "F"
- **Velocity vector:** Blue arrow with diamond arrowhead, labeled "v"
- **Orbital trail:** Color-coded by speed (blue=slow, green=medium, red=fast)
- **Distance marker:** Dashed line between bodies with distance label
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

The simulation adapts to student performance:

- **Standard:** Default learning pace with regular assessments
- **Accelerated:** Faster pace for students showing mastery
- **Remedial:** Slower pace with more support for struggling students
- **Misconception Intervention:** Targeted feedback when misconceptions detected

## Accessibility

- Full keyboard navigation
- ARIA labels on all interactive elements
- Screen reader announcements for state changes
- Color vision accessibility (shape differentiation for vectors)
- WCAG AA contrast ratios
- Adjustable font size

## Technical Implementation

- **Rendering:** Three.js (WebGL)
- **Physics:** Custom Velocity Verlet integrator
- **Audio:** None (visual simulation)
- **Storage:** None (sandboxed, no localStorage)
- **External dependencies:** Three.js r152 (CDN)
- **Output:** Single self-contained HTML file

## Browser Compatibility

- Chrome/Edge 90+
- Firefox 88+
- Safari 14+

Requires WebGL support.
