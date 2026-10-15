# Architecture Blueprint

---

## 1. Document Title & Metadata

| Field | Value |
|---|---|
| Document Title | Architecture Blueprint |
| Version | 1.0 |
| Date | September 2, 2026 |
| Reference Specification | AI Focus Specification v1.0 — "Gravitational Fields and Orbital Mechanics: Interactive Learning Laboratory" |
| Subject | Physics (Classical Mechanics) |
| Topic | Gravitational Fields and Orbital Mechanics |
| Architecture Purpose | Complete implementation blueprint enabling a Builder to develop the application without making architectural decisions |

---

## 2. Technology Stack Decision

### 2.1 Language: TypeScript (5.x)

**Choice:** TypeScript 5.x with strict mode enabled.

**Justification:**
- Type safety prevents runtime errors in physics calculations where numerical precision matters.
- Excellent IDE support accelerates development of complex simulation logic.
- JavaScript ecosystem provides mature libraries for 3D rendering, state management, and testing.
- Browser-native runtime eliminates compilation-to-native overhead; the application runs wherever a modern browser runs.
- Interface definitions enforce contracts between the physics engine, rendering pipeline, and UI layer.

### 2.2 3D Engine: Three.js (r168+)

**Choice:** Three.js as the 3D rendering library.

**Justification:**
- Mature WebGL/WebGPU abstraction layer with battle-tested performance.
- Scene graph architecture maps naturally to the simulation's entity hierarchy (central body, orbiting object, vectors, trails).
- Built-in geometry primitives (SphereGeometry, ArrowHelper, Line, BufferGeometry) cover all visualization needs.
- Extensive shader material system enables color-coded trajectory trails and vector rendering without custom WebGL code.
- Large community and documentation reduce implementation risk.
- WebGPU renderer available as future optimization path without API changes.
- No heavy engine overhead (unlike Unity/Unreal) — the application does not need a full game engine.

### 2.3 UI Framework: React 18+

**Choice:** React 18 with functional components and hooks.

**Justification:**
- Component-based architecture composes cleanly with Three.js via @react-three/fiber (R3F) for declarative 3D scene management.
- Built-in accessibility primitives (ARIA attributes, focus management, keyboard event handling) align with the specification's accessibility requirements.
- Virtual DOM diffing efficiently updates readout panels without re-rendering the entire 3D scene.
- Zustand integration is seamless for shared state between UI panels and simulation.
- Large ecosystem of accessibility testing tools (axe-core, React Testing Library).

### 2.4 State Management: Zustand (4.x)

**Choice:** Zustand as the primary state management library.

**Justification:**
- Minimal boilerplate — critical for a state-heavy simulation with dozens of reactive variables.
- Slice pattern naturally separates simulation state, UI state, learner progress state, and assessment state.
- Middleware support for persistence (localStorage) enables session resume.
- No provider wrapper overhead — direct store access from any component including Three.js scene objects.
- TypeScript-first design with excellent inference for complex state shapes.

### 2.5 Build Tool: Vite (5.x)

**Choice:** Vite as the development server and production bundler.

**Justification:**
- Native ESM dev server provides instant hot module replacement during development.
- esbuild-based TypeScript transpilation is orders of magnitude faster than tsc for development iterations.
- Rollup-based production builds produce optimized, tree-shaken bundles.
- Plugin ecosystem covers all needs: React, TypeScript, testing, linting.
- Environment variable handling for configuration (physics constants, simulation scale).

### 2.6 Testing Frameworks

| Layer | Tool | Justification |
|---|---|---|
| Unit Testing | Vitest (2.x) | Vite-native, fast execution, ESM-first, compatible with Three.js mocking |
| Component Testing | React Testing Library + Vitest | Tests UI component behavior, not implementation details; accessibility-focused |
| Integration Testing | Vitest + Custom harness | Verifies physics engine → rendering pipeline data flow end-to-end |
| E2E Testing | Playwright (1.x) | Cross-browser testing; verifies full learner journey including keyboard navigation |
| Accessibility Testing | axe-core + Playwright | Automated WCAG compliance scanning on every page state |

### 2.7 Supporting Libraries

| Library | Version | Purpose | Justification |
|---|---|---|---|
| @react-three/fiber | 8.x | Declarative Three.js in React | Eliminates imperative scene management; React reconciler handles mount/unmount of 3D objects |
| @react-three/drei | 9.x | Three.js helper components | OrbitControls, Text, Line, Html overlays reduce custom Three.js boilerplate |
| zustand | 4.x | State management | See §2.4 |
| react-aria | 3.x | Accessible UI primitives | Provides WAI-ARIA compliant slider, dialog, and button components with full keyboard/screen reader support |
| i18next | 23.x | Internationalization | Text externalization for localization; all UI strings managed outside components |

### 2.8 Development Tooling

| Tool | Purpose |
|---|---|
| ESLint (flat config) | Code quality with TypeScript and React rules |
| Prettier | Consistent formatting |
| Husky + lint-staged | Pre-commit quality gates |
| Storybook 8 | Component development and visual testing |
| chromatic | Visual regression testing for 3D scene captures |

### 2.9 Technology Stack Summary

```
┌─────────────────────────────────────────────────────┐
│                   Application                       │
├──────────────┬──────────────┬───────────────────────┤
│  React 18+   │ Three.js     │  Custom Physics       │
│  (UI Layer)  │ r168+        │  Engine               │
│              │ via R3F      │  (TypeScript)         │
├──────────────┴──────────────┴───────────────────────┤
│              Zustand 4.x (State Management)          │
├─────────────────────────────────────────────────────┤
│              TypeScript 5.x (Language)               │
├─────────────────────────────────────────────────────┤
│              Vite 5.x (Build & Dev Server)           │
├─────────────────────────────────────────────────────┤
│              Vitest / Playwright (Testing)            │
└─────────────────────────────────────────────────────┘
```

---

## 3. System Architecture Overview

### 3.1 Architecture Style: Layered Architecture with Event-Driven Simulation Loop

The application follows a **layered architecture** with three primary layers, connected through a **central event bus** and **shared state stores**. The simulation loop operates as an independent event-driven system that publishes state changes consumed by both rendering and UI layers.

### 3.2 High-Level Component Diagram

```
┌──────────────────────────────────────────────────────────────┐
│                        PRESENTATION LAYER                     │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────┐  │
│  │  React UI   │  │  Three.js    │  │  Accessible        │  │
│  │  Panels     │  │  3D Scene    │  │  Overlays          │  │
│  │  (Readouts, │  │  (Central    │  │  (Screen reader    │  │
│  │  Controls,  │  │  body, orbit,│  │  announcements,    │  │
│  │  Prompts)   │  │  vectors,    │  │  ARIA labels)      │  │
│  │             │  │  trails)     │  │                    │  │
│  └──────┬──────┘  └──────┬───────┘  └────────┬───────────┘  │
│         │                │                     │              │
├─────────┴────────────────┴─────────────────────┴──────────────┤
│                        STATE LAYER                             │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────┐  │
│  │  Simulation  │  │  UI State    │  │  Learner Progress  │  │
│  │  Store       │  │  Store       │  │  Store             │  │
│  │  (position,  │  │  (phase,     │  │  (pathway, scores, │  │
│  │  velocity,   │  │  panels,     │  │  misconceptions,   │  │
│  │  force,      │  │  controls,   │  │  phase completion) │  │
│  │  derived)    │  │  readouts)   │  │                    │  │
│  └──────┬───────┘  └──────┬───────┘  └────────┬───────────┘  │
│         │                │                     │              │
├─────────┴────────────────┴─────────────────────┴──────────────┤
│                        LOGIC LAYER                             │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────┐  │
│  │  Physics     │  │  Orbital     │  │  Assessment &      │  │
│  │  Engine      │  │  Parameter   │  │  Adaptive Pathway  │  │
│  │  (gravity,   │  │  Calculator  │  │  Engine            │  │
│  │  integration,│  │  (Keplerian  │  │  (predictions,     │  │
│  │  force       │  │  elements,   │  │  misconceptions,   │  │
│  │  computation)│  │  period,     │  │  routing)          │  │
│  │              │  │  energy)     │  │                    │  │
│  └──────────────┘  └──────────────┘  └────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

### 3.3 Data Flow

1. **User Interaction** → User manipulates controls (velocity slider, position drag, parameter input).
2. **State Update** → Interaction handler updates the appropriate Zustand store (simulation parameters or UI state).
3. **Physics Tick** → On each animation frame, the simulation store dispatches a physics step to the Physics Engine.
4. **Physics Computation** → Engine computes new position, velocity, force, and derived quantities (energy, orbital parameters).
5. **State Commit** → Computed results are committed to the Simulation Store.
6. **Rendering** → Three.js scene graph (via R3F) subscribes to the Simulation Store and re-renders affected objects.
7. **UI Update** → React UI panels subscribe to the Simulation Store and re-render readouts.
8. **Assessment Check** → Adaptive Pathway Engine evaluates learner actions against assessment triggers and updates the Learner Progress Store.
9. **Feedback Delivery** → Feedback system reads assessment results and displays appropriate feedback through UI panels.

### 3.4 Key Architectural Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Rendering integration | @react-three/fiber declarative scene | Eliminates imperative Three.js scene management; React handles lifecycle |
| Physics as pure function | `computePhysicsStep(state, dt) → newState` | Testable, deterministic, no side effects, trivially unit-testable |
| State as single source of truth | Zustand stores | Both rendering and UI subscribe to the same store, ensuring consistency |
| Assessment decoupled from UI | Separate engine module | Assessment logic can be tested independently of rendering |
| Feedback as data | Feedback objects in store | Decouples "what to show" from "how to show it"; enables localization |

---

## 4. Project Structure

### 4.1 Directory Layout

```
orbital-physics-lab/
├── public/
│   ├── textures/
│   │   ├── central-body-diffuse.png        # Central body surface texture
│   │   ├── central-body-normal.png         # Normal map for surface detail
│   │   └── orbiting-body-diffuse.png       # Orbiting object texture
│   ├── models/
│   │   └── (none — geometry generated procedurally)
│   └── fonts/
│       └── (system fonts used via CSS)
├── src/
│   ├── main.tsx                            # Application entry point
│   ├── App.tsx                             # Root component; phase router
│   ├── vite-env.d.ts                       # Vite type declarations
│   │
│   ├── config/
│   │   ├── physics.ts                      # Gravitational constant G, simulation scale, integration parameters
│   │   ├── simulation.ts                   # Default parameter ranges, initial conditions
│   │   ├── visualization.ts                # Vector scale factors, trail colors, camera defaults
│   │   └── phases.ts                       # Phase definitions, sequencing rules, transition triggers
│   │
│   ├── engine/
│   │   ├── physics/
│   │   │   ├── gravity.ts                  # Gravitational force computation: F = GMm/r²
│   │   │   ├── integrator.ts              # Velocity Verlet numerical integrator
│   │   │   ├── orbital-parameters.ts       # Keplerian element computation from state vectors
│   │   │   ├── energy.ts                   # Kinetic, potential, and total energy computation
│   │   │   ├── escape-velocity.ts          # Escape velocity computation at a given distance
│   │   │   └── types.ts                    # Physics state interfaces (Vector3, BodyState, ForceResult)
│   │   │
│   │   ├── assessment/
│   │   │   ├── triggers.ts                 # Formative assessment trigger definitions and evaluation
│   │   │   ├── predictions.ts              # Prediction task management and correctness evaluation
│   │   │   ├── misconceptions.ts           # Misconception detection logic and intervention routing
│   │   │   ├── scoring.ts                  # Mastery scoring and threshold evaluation
│   │   │   └── types.ts                    # Assessment interfaces (Trigger, Prediction, Score)
│   │   │
│   │   ├── adaptive/
│   │   │   ├── pathway-engine.ts           # Pathway routing logic (Standard, Accelerated, Remedial, Misconception)
│   │   │   ├── performance-tracker.ts      # Learner performance metrics aggregation
│   │   │   └── types.ts                    # Pathway and performance interfaces
│   │   │
│   │   ├── feedback/
│   │   │   ├── feedback-store.ts           # Feedback content registry (corrective, explanatory, motivational, elaborative)
│   │   │   ├── delivery.ts                 # Feedback display timing and sequencing logic
│   │   │   └── types.ts                    # Feedback interfaces
│   │   │
│   │   └── orchestration/
│   │       ├── simulation-loop.ts          # Main animation loop, fixed timestep, speed control
│   │       └── event-bus.ts               # Typed event emitter for inter-module communication
│   │
│   ├── stores/
│   │   ├── simulation-store.ts             # Central body, orbiting body, vectors, forces, derived quantities
│   │   ├── ui-store.ts                     # Active panel, readout configuration, camera mode, 2D/3D toggle
│   │   ├── learner-store.ts               # Current phase, pathway, assessment scores, misconception log
│   │   └── feedback-store.ts              # Active feedback queue, dismissed feedback history
│   │
│   ├── scene/
│   │   ├── SimulationScene.tsx             # R3F Canvas wrapper; scene graph root
│   │   ├── CentralBody.tsx                # Central body mesh, material, and mass visualization
│   │   ├── OrbitingBody.tsx               # Orbiting object mesh, position binding
│   │   ├── ForceVector.tsx                # Gravitational force arrow (ArrowHelper-based)
│   │   ├── VelocityVector.tsx             # Velocity arrow (ArrowHelper-based, distinct arrowhead)
│   │   ├── OrbitalTrail.tsx               # Trajectory trail line geometry, color-coded by speed
│   │   ├── DistanceMarker.tsx             # Line between bodies with distance label
│   │   ├── ReferencePlane.tsx             # Translucent orbital plane disc
│   │   ├── TrajectoryClassifier.tsx       # Dynamic label component (Circular/Elliptical/Escape)
│   │   ├── CameraController.tsx           # OrbitControls wrapper with keyboard bindings
│   │   └── SceneLighting.tsx              # Ambient + directional light setup
│   │
│   ├── ui/
│   │   ├── layout/
│   │   │   ├── AppShell.tsx                # Main layout: 3D canvas + side panel + top bar
│   │   │   ├── TopBar.tsx                  # Phase indicator, progress tracker, settings gear
│   │   │   └── SidePanel.tsx               # Collapsible right panel for readouts and controls
│   │   │
│   │   ├── panels/
│   │   │   ├── ReadoutPanel.tsx            # Live orbital data display (distance, force, speed, period, eccentricity, semi-major axis)
│   │   │   ├── ControlPanel.tsx            # Sliders for distance, velocity magnitude, velocity direction, masses
│   │   │   ├── PhasePanel.tsx              # Phase-specific content: instructions, prompts, tasks
│   │   │   └── FeedbackPanel.tsx           # Feedback message display with dismiss/skip
│   │   │
│   │   ├── assessment/
│   │   │   ├── PredictionDialog.tsx        # "What will happen?" input before simulation run
│   │   │   ├── ExplanationPrompt.tsx       # Open-ended explanation text input
│   │   │   ├── ClassificationTask.tsx      # Circular/Elliptical/Escape selection buttons
│   │   │   ├── MisconceptionProbe.tsx      # Targeted misconception question component
│   │   │   └── MasteryGate.tsx             # Phase completion / retry routing display
│   │   │
│   │   ├── controls/
│   │   │   ├── VelocitySlider.tsx          # Accessible slider for velocity magnitude (react-aria)
│   │   │   ├── DirectionWheel.tsx          # Angle selector for velocity direction
│   │   │   ├── MassControl.tsx             # Central body and satellite mass adjustment
│   │   │   ├── SpeedControl.tsx            # Simulation speed multiplier (0.25×–4×)
│   │   │   └── Button.tsx                  # Styled, accessible button with loading states
│   │   │
│   │   └── accessibility/
│   │       ├── ScreenReaderAnnouncer.tsx   # Live region for dynamic state announcements
│   │       ├── KeyboardHelp.tsx            # Keyboard shortcuts overlay
│   │       └── FontSizeControl.tsx         # Readout text size selector (small/medium/large)
│   │
│   ├── hooks/
│   │   ├── useSimulationLoop.ts            # Hook connecting animation frame to physics engine
│   │   ├── usePhaseManager.ts             # Hook managing phase transitions and gating
│   │   ├── useAssessment.ts               # Hook connecting assessment triggers to learner store
│   │   ├── useKeyboardNavigation.ts       # Hook for 3D space keyboard controls
│   │   ├── useAccessibility.ts            # Hook for screen reader announcements and focus management
│   │   └── useScreenReaderAnnounce.ts     # Hook for programmatic screen reader announcements
│   │
│   ├── i18n/
│   │   ├── index.ts                       # i18next initialization and configuration
│   │   └── locales/
│   │       ├── en.json                    # English translations (primary)
│   │       └── (additional locales added later)
│   │
│   ├── utils/
│   │   ├── vector-math.ts                 # Vector3 operations (add, subtract, scale, magnitude, normalize, dot, cross)
│   │   ├── formatting.ts                  # Number formatting for readouts (significant figures, units)
│   │   ├── constants.ts                   # Physical constants in simulation units
│   │   └── type-guards.ts                # Runtime type narrowing utilities
│   │
│   └── types/
│       ├── physics.ts                     # Core physics type definitions
│       ├── simulation.ts                  # Simulation configuration types
│       ├── assessment.ts                  # Assessment and scoring types
│       ├── pathway.ts                     # Adaptive pathway types
│       └── ui.ts                          # UI state types
│
├── tests/
│   ├── unit/
│   │   ├── engine/physics/
│   │   │   ├── gravity.test.ts
│   │   │   ├── integrator.test.ts
│   │   │   ├── orbital-parameters.test.ts
│   │   │   ├── energy.test.ts
│   │   │   └── escape-velocity.test.ts
│   │   ├── engine/assessment/
│   │   │   ├── triggers.test.ts
│   │   │   ├── predictions.test.ts
│   │   │   ├── misconceptions.test.ts
│   │   │   └── scoring.test.ts
│   │   ├── engine/adaptive/
│   │   │   └── pathway-engine.test.ts
│   │   └── utils/
│   │       └── vector-math.test.ts
│   ├── integration/
│   │   ├── physics-rendering.test.ts       # Physics state → scene graph update pipeline
│   │   ├── assessment-flow.test.ts         # Trigger → scoring → pathway routing pipeline
│   │   └── phase-transitions.test.ts       # Phase gating and transition logic
│   ├── e2e/
│   │   ├── phase-1-exploration.spec.ts
│   │   ├── phase-2-inverse-square.spec.ts
│   │   ├── phase-3-orbital-dynamics.spec.ts
│   │   ├── phase-4-synthesis.spec.ts
│   │   ├── accessibility.spec.ts
│   │   └── keyboard-navigation.spec.ts
│   └── accessibility/
│       ├── wcag-compliance.spec.ts         # axe-core automated scans
│       └── screen-reader.spec.ts           # Screen reader announcement verification
│
├── index.html                              # Vite HTML entry point
├── package.json
├── tsconfig.json
├── tsconfig.node.json
├── vite.config.ts
├── vitest.config.ts
├── playwright.config.ts
├── .eslintrc.cjs
├── .prettierrc
└── README.md
```

### 4.2 Module Dependency Rules

1. **Engine modules** (`src/engine/`) must NOT import from `src/scene/` or `src/ui/`. They are pure logic.
2. **Scene modules** (`src/scene/`) may import from `src/stores/` and `src/engine/physics/` types only.
3. **UI modules** (`src/ui/`) may import from `src/stores/` and `src/engine/` types only.
4. **Stores** (`src/stores/`) may import from `src/types/` and `src/config/` only.
5. **Hooks** (`src/hooks/`) bridge between stores, engine, and components but contain no rendering logic.
6. **No circular dependencies** between any top-level directories.

---

## 5. Physics Engine Design

### 5.1 Gravitational Force Model

The gravitational force between the central body and orbiting object is computed using Newton's law of universal gravitation:

```
F = G * M * m / r²
```

Where:
- `G` is the gravitational constant (scaled to simulation units)
- `M` is the central body mass
- `m` is the orbiting object mass
- `r` is the distance between centers

**Critical implementation detail:** The force direction always points along the line connecting the two mass centers, toward the central body. This is a unit vector computation:

```
direction = normalize(centralBody.position - orbitingBody.position)
forceVector = direction * (G * M * m / r²)
```

### 5.2 Numerical Integration: Velocity Verlet

**Choice:** Velocity Verlet (leapfrog) integrator rather than Euler or Runge-Kutta.

**Justification:**
- **Symplectic property:** Velocity Verlet conserves the structure of Hamiltonian systems, meaning orbits do not artificially spiral inward or outward over long durations. This is critical for educational accuracy — a learner must see stable circular orbits remain stable.
- **Time-reversible:** Improves accuracy for oscillatory (orbital) motion.
- **Second-order accuracy:** O(dt²) error per step, sufficient for the simulation's timescale.
- **Computational cost:** Identical to Euler method (one force evaluation per step), no additional cost for dramatically better accuracy.
- **Energy conservation:** Total energy drift is bounded rather than growing monotonically, which is essential for Objective 4 (Energy Conservation).

**Integration algorithm:**

```
1. Compute force at current position: F(t)
2. Update position: r(t+dt) = r(t) + v(t)*dt + 0.5*a(t)*dt²
3. Compute force at new position: F(t+dt)
4. Update velocity: v(t+dt) = v(t) + 0.5*(a(t) + a(t+dt))*dt
```

Where `a = F/m` (acceleration derived from force).

### 5.3 Fixed Timestep with Accumulator

The simulation uses a **fixed physics timestep** of 1/120 seconds (120 Hz physics) with a **frame-rate-independent accumulator**. This ensures:
- Deterministic physics regardless of display refresh rate.
- Consistent behavior across devices (60 Hz, 120 Hz, 144 Hz monitors).
- Stable integration at high simulation speeds.

```
accumulator += realDeltaTime * simulationSpeed
while (accumulator >= FIXED_DT):
    state = physicsStep(state, FIXED_DT)
    accumulator -= FIXED_DT
interpolatedState = lerp(previousState, state, accumulator / FIXED_DT)
```

The interpolated state is used for rendering to ensure smooth visual motion between physics steps.

### 5.4 Orbital Parameter Computation

Orbital parameters are derived from the position and velocity state vectors using vis-viva and Keplerian element equations:

**Semi-major axis (a):**
```
a = 1 / (2/r - v²/(G*M))
```

**Eccentricity (e):**
```
e = sqrt(1 - (h²/(G*M*a)))
```
Where `h = |r × v|` is the specific angular momentum.

**Orbital period (T):**
```
T = 2π * sqrt(a³/(G*M))
```
(Kepler's third law)

**Escape velocity at distance r:**
```
v_esc = sqrt(2*G*M/r)
```

**Trajectory classification logic:**
- If `|r|` is approximately constant (within tolerance) and `|v|` is approximately constant: **Circular**
- If `a > 0` and `0 ≤ e < 1`: **Elliptical**
- If `e ≥ 1` or total energy ≥ 0: **Escape**

**Tolerance thresholds:**
- Eccentricity < 0.02 is classified as circular.
- Total energy ≥ -0.001 (in simulation units) is classified as escape.
- These thresholds are configurable in `src/config/physics.ts`.

### 5.5 Energy Computation

```
KE = 0.5 * m * v²
PE = -G * M * m / r
TotalEnergy = KE + PE
```

These are computed every frame and stored for display and assessment purposes.

### 5.6 Physics State Interface

```typescript
interface PhysicsState {
  centralBody: {
    position: Vector3;      // Fixed at origin (0, 0, 0)
    mass: number;           // In simulation mass units
    radius: number;         // Visual radius (does not affect physics)
  };
  orbitingBody: {
    position: Vector3;      // Current position
    velocity: Vector3;      // Current velocity vector
    mass: number;           // Satellite mass (for force computation, but does not affect trajectory when << M)
  };
  derived: {
    force: Vector3;          // Gravitational force on orbiting body
    forceMagnitude: number;  // |force|
    speed: number;           // |velocity|
    distance: number;        // |position - centralBody.position|
    kineticEnergy: number;
    potentialEnergy: number;
    totalEnergy: number;
    semiMajorAxis: number;
    eccentricity: number;
    orbitalPeriod: number;
    escapeVelocity: number;
    trajectoryType: 'circular' | 'elliptical' | 'escape';
    periapsisSpeed: number;
    apoapsisSpeed: number;
  };
  trail: Vector3[];          // Position history for trail rendering
  timeElapsed: number;       // Total simulation time
}
```

### 5.7 Educational Constraints (Inherited from Specification)

- **Two-body only:** No n-body simulation. Single central body, single orbiting object.
- **No tidal forces, no drag, no relativistic effects.** Pure Newtonian gravity.
- **Orbital plane is 2D** (XY plane) rendered in 3D for depth perception. Velocity direction is within this plane.
- **Object cannot be placed inside the central body.** Minimum distance enforced (1.5 units from center).
- **Mass independence demonstration:** When satellite mass is varied, the trajectory remains identical (for satellite mass << central body mass). The force magnitude changes but acceleration (and thus trajectory) does not.

---

## 6. Rendering Pipeline

### 6.1 Scene Graph Structure

```
SimulationScene (R3F Canvas)
├── SceneLighting
│   ├── AmbientLight (intensity: 0.3)
│   └── DirectionalLight (intensity: 0.8, position: [10, 10, 5])
├── ReferencePlane (translucent disc at z=0)
├── CentralBody
│   └── SphereGeometry + MeshStandardMaterial (with texture)
├── OrbitingBody
│   └── SphereGeometry + MeshStandardMaterial
├── ForceVector (ArrowHelper)
├── VelocityVector (ArrowHelper, distinct arrowhead style)
├── OrbitalTrail (BufferGeometry Line with color attribute)
├── DistanceMarker (Line + Html label)
├── TrajectoryClassifier (Html label)
└── CameraController (OrbitControls)
```

### 6.2 Camera Configuration

- **Type:** Perspective camera, FOV 50°.
- **Initial position:** [0, 8, 12] looking at origin.
- **Controls:** OrbitControls from @react-three/drei with:
  - Keyboard bindings: Arrow keys for rotation, +/- for zoom, Shift+arrows for pan.
  - Right-click drag for pan.
  - Scroll wheel for zoom.
  - Touch support: single-finger rotate, two-finger pinch zoom, three-finger pan.
  - Damping enabled for smooth motion.
  - Min/max distance limits: 3 to 50 units.
  - Constrained polar angle (prevent flipping): 10° to 170°.

### 6.3 Lighting

- **Ambient light:** Soft fill to prevent fully dark surfaces, intensity 0.3.
- **Directional light:** Simulates a distant light source, provides depth cues on spherical bodies, intensity 0.8.
- **No point lights:** Unnecessary for the scene's scope; the two bodies are the only objects.
- **Environment map:** Optional HDRI environment for subtle reflections on the spheres, loaded from public/textures/.

### 6.4 Materials

| Object | Material | Properties |
|---|---|---|
| Central body | MeshStandardMaterial | Texture-mapped (diffuse + normal), roughness 0.7, metalness 0.1. Mass represented by color intensity (configurable). |
| Orbiting body | MeshStandardMaterial | Solid color (distinguishable from central body), roughness 0.5, metalness 0.2. |
| Force vector | Custom shader or MeshBasicMaterial | Solid color, no lighting interaction, always visible. Arrow cone + cylinder geometry. |
| Velocity vector | Custom shader or MeshBasicMaterial | Distinct color from force vector. **Different arrowhead style** (see §7) for color vision accessibility. |
| Orbital trail | LineBasicMaterial with vertex colors | Color gradient encoding speed (cooler = slower, warmer = faster). Opacity fades from head (opaque) to tail (transparent). |
| Reference plane | MeshBasicMaterial | Translucent (opacity 0.08), neutral color, no depth writing. |
| Distance marker | LineBasicMaterial | Neutral color, thin line. |

### 6.5 Rendering Optimization

- **No post-processing effects** — unnecessary for the educational content and adds GPU cost.
- **Frustum culling** enabled (Three.js default) — though with only a few objects, this is minimal.
- **No shadows** — adds visual quality but not needed for educational objectives; saves significant GPU cost.
- **Geometry instancing** not needed (only two sphere objects).
- **Trail geometry** uses a pre-allocated BufferGeometry with a maximum vertex count (e.g., 2000 points). When the trail exceeds this length, the oldest vertices are overwritten in a circular buffer pattern. This prevents garbage collection pauses.

---

## 7. Vector Visualization System

### 7.1 Force Vector

**Rendering:** Three.js `ArrowHelper` or custom `ConeGeometry` + `CylinderGeometry` group.

**Properties:**
- **Origin:** Center of the orbiting body mesh.
- **Direction:** Toward the central body center (computed from position difference).
- **Length:** Proportional to force magnitude, scaled by a configurable factor (`FORCE_VECTOR_SCALE` in `src/config/visualization.ts`). The scale factor ensures the arrow is visible at maximum distance but does not become overwhelmingly large at minimum distance.
- **Clamping:** Maximum arrow length capped at 4 units, minimum at 0.3 units, to maintain visibility at all distances.
- **Color:** A distinct, accessible color (e.g., `#E74C3C` red) that passes WCAG contrast against the dark space background.
- **Label:** Text label "F" or "Gravitational Force" positioned at the arrowhead. Always visible.

### 7.2 Velocity Vector

**Rendering:** Same geometry as force vector but with a **distinct visual treatment** for color vision accessibility.

**Accessibility differentiation:**
- **Arrowhead shape:** Force vector uses a standard cone arrowhead; velocity vector uses a **flat, diamond-shaped arrowhead** (rotated square geometry). This ensures the vectors are distinguishable by shape, not just color.
- **Line style:** Velocity vector line is slightly thicker or uses a different opacity.
- **Color:** Distinct from force vector (e.g., `#3498DB` blue).

**Properties:**
- **Origin:** Center of the orbiting body mesh.
- **Direction:** Along the velocity vector.
- **Length:** Proportional to speed, scaled by `VELOCITY_VECTOR_SCALE`.
- **Clamping:** Same range as force vector for visual consistency.
- **Label:** Text label "v" or "Velocity" positioned at the arrowhead.

### 7.3 Vector Update Frequency

Vectors are updated every rendering frame (not every physics step) to ensure smooth visual motion. The vector components (direction, length) are read from the latest interpolated physics state.

### 7.4 Vector Visibility Control

Vectors can be toggled on/off via the UI to reduce visual clutter during certain phases. Default visibility:
- **Phase 1:** Force vector visible, velocity vector hidden.
- **Phase 2:** Force vector visible, velocity vector hidden (distance experiment).
- **Phase 3:** Both vectors visible (orbital dynamics requires seeing the angle between them).
- **Phase 4:** Both vectors visible, can be toggled by learner.

The UI toggle state is managed in the `ui-store`.

---

## 8. Orbital Path Tracing System

### 8.1 Trail Implementation

**Geometry:** `THREE.BufferGeometry` with a pre-allocated position buffer of `MAX_TRAIL_POINTS` (2000) vertices. The trail is rendered as a `THREE.Line` with `LineBasicMaterial`.

**Color encoding:** Vertex colors encode speed at each trail point. A color gradient function maps normalized speed (0 to max speed) to a color palette:
- **Slow:** Cool color (blue `#2980B9`)
- **Medium:** Neutral color (green `#27AE60`)
- **Fast:** Warm color (orange-red `#E74C3C`)

The color gradient is defined in `src/config/visualization.ts` and uses THREE.Color interpolation.

**Opacity encoding:** Trail opacity fades from full opacity at the head (most recent position) to zero at the tail (oldest position). This is achieved by setting vertex alpha values in the buffer or by using a custom shader material.

### 8.2 Trail Lifecycle

1. **Trail recording** is active whenever the simulation is running.
2. **Position buffer management:** New positions are appended to the buffer. When `MAX_TRAIL_POINTS` is reached, the oldest positions are overwritten in a circular buffer pattern. The buffer start index tracks the oldest valid point.
3. **Trail reset:** When the learner changes initial conditions (resets the orbit), the trail buffer is cleared.
4. **Trail pause:** When the simulation is paused, no new trail points are added.

### 8.3 Trail for Escape Trajectories

For escape trajectories, the trail extends outward from the central body. To prevent the trail from becoming infinitely long:
- The trail is allowed to extend to `MAX_TRAIL_POINTS` and then stops recording.
- The visual fading effect ensures the oldest portion of the trail is invisible, creating a natural "departure" appearance.
- A label or visual indicator may note "Escape trajectory" at the trail end.

### 8.4 Trail Rendering Performance

- The trail is a single draw call (one `Line` object with many vertices).
- Vertex buffer is updated via `geometry.attributes.position.needsUpdate = true` and `geometry.attributes.color.needsUpdate = true` each frame.
- No new geometry is allocated during normal simulation — only buffer attribute updates.

---

## 9. Live Data Readout System

### 9.1 Readout Panel Structure

The readout panel (`ReadoutPanel.tsx`) displays the following quantities, updated every frame:

| Quantity | Label | Units | Format | Phase Visibility |
|---|---|---|---|---|
| Distance | "Distance from Center" | Simulation units (u) | 2 decimal places | Phase 1+ |
| Force Magnitude | "Gravitational Force" | Newtons (N) (scaled) | 2 decimal places | Phase 1+ |
| Speed | "Orbital Speed" | u/s | 2 decimal places | Phase 3+ |
| Orbital Period | "Orbital Period" | seconds (s) | 1 decimal place | Phase 3+ (after 1 orbit) |
| Eccentricity | "Eccentricity" | dimensionless | 3 decimal places | Phase 3+ |
| Semi-major Axis | "Semi-major Axis" | u | 2 decimal places | Phase 3+ |
| Kinetic Energy | "Kinetic Energy" | Joules (J) (scaled) | 2 decimal places | Phase 3+ (optional toggle) |
| Potential Energy | "Potential Energy" | J (scaled) | 2 decimal places | Phase 3+ (optional toggle) |
| Escape Velocity | "Escape Velocity" | u/s | 2 decimal places | Phase 3+ |

### 9.2 Readout Computation

All readout values are computed by the physics engine and stored in `PhysicsState.derived`. The readout panel simply reads from the store. No computation occurs in the UI layer.

### 9.3 Progressive Disclosure

Readouts are introduced gradually to manage cognitive load (per §9 of the specification):
- **Phase 1:** Distance and Force Magnitude only.
- **Phase 2:** Distance and Force Magnitude (with data recording table).
- **Phase 3:** All six primary readouts (distance, force, speed, period, eccentricity, semi-major axis). Energy readouts available via toggle.
- **Phase 4:** All readouts available.

Phase-based visibility is controlled by the `ui-store` which tracks the current phase and enables/disables readout sections accordingly.

### 9.4 Screen Reader Support

Every readout value has an associated `aria-label` and is wrapped in an element with `role="status"` so screen readers announce changes. The text format for screen readers is:
- "Distance from central body: 3.2 units"
- "Gravitational force: 4.7 Newtons, toward central body"
- "Orbital speed: 2.1 units per second"

A `ScreenReaderAnnouncer` component uses an ARIA live region (`aria-live="polite"`) to periodically announce the full state summary (every 5 seconds during simulation, or on demand).

### 9.5 Data Recording Table (Phase 2)

During the distance experiment (Phase 2), the learner records distance and force values in a table. This table is implemented as a React component that accumulates rows as the learner clicks "Record" at each distance. The table stores entries in the learner store and allows the learner to review the data for pattern recognition.

---

## 10. User Interaction System

### 10.1 Object Placement

**Implementation:** The orbiting body's initial position is set via:
1. **Slider controls:** The learner adjusts the initial distance using a `react-aria` Slider component. The position is set along a default axis (e.g., positive X-axis) at the specified distance from the central body.
2. **Angle selector:** A circular angle selector (DirectionWheel component) allows the learner to set the initial angular position around the central body. Default: 0° (positive X-axis).
3. **Keyboard:** Arrow keys adjust distance (left/right) and angle (up/down) when the control panel has focus.

**Constraint enforcement:** The position is clamped to the range [1.5, 10] simulation units. Positions inside the central body radius are rejected with a tooltip message.

### 10.2 Velocity Adjustment

**Implementation:** The orbiting body's initial velocity is set before the simulation runs (or after a reset). Controls:

1. **Velocity magnitude slider:** Range [0, 3× circular orbit speed]. The slider displays the value as a multiplier of the circular orbit speed at the current distance (e.g., "1.0× circular speed"). This makes the relationship between velocity and trajectory type immediately interpretable.
2. **Velocity direction wheel:** Angle selector for the velocity direction within the orbital plane. Default: perpendicular to the radius vector (90°), which produces a circular orbit.
3. **Keyboard:** Corresponding arrow key adjustments when the control has focus.

**Circular orbit speed computation (displayed on the slider):**
```
v_circular = sqrt(G * M / r)
```

This value is computed in real time as the distance changes, so the slider's reference point updates dynamically.

### 10.3 3D Space Navigation

**Controls (via OrbitControls):**
- **Rotate:** Left-click drag, or Arrow keys when canvas has focus.
- **Zoom:** Scroll wheel, or +/- keys.
- **Pan:** Right-click drag, or Shift+Arrow keys.
- **Touch:** Single finger rotate, two-finger pinch zoom, three-finger pan.

**Teaching controls to the learner:** Phase 1 begins with an explicit tutorial overlay that highlights each control and lets the learner practice. The tutorial is skippable for returning users (checked via localStorage flag).

### 10.4 Simulation Control

| Action | Button | Keyboard | Effect |
|---|---|---|---|
| Start simulation | Play button | Space | Begins physics simulation from current initial conditions |
| Pause simulation | Pause button | Space (toggle) | Freezes physics at current state |
| Reset | Reset button | R | Returns orbiting body to initial conditions, clears trail |
| Speed up | Speed + button | ] | Increases simulation speed (0.25× → 0.5× → 1× → 2× → 4×) |
| Speed down | Speed - button | [ | Decreases simulation speed |

### 10.5 Mass Controls

- **Central body mass:** Slider, range [1×, 10× reference mass]. Default: 1×. Affects force magnitude and orbital speed.
- **Satellite mass:** Slider, range [0.1×, 10× reference mass]. Default: 1×. Changes force magnitude display but does NOT change trajectory (for educational demonstration of mass independence).

### 10.6 Constraint-Based Exploration

Per §10.7 of the specification, exploration is bounded:
- Cannot place orbiting object inside the central body (minimum distance enforced).
- Cannot assign velocity vectors that point through the central body center without first providing tangential component (prevents confusing "falling straight through" scenarios unless intentionally requested).
- Simulation speed is bounded to [0.25×, 4×] to prevent unintelligible fast-forward.
- Trail length is bounded (see §8).

---

## 11. Simulation Loop & Timing

### 11.1 Main Loop Architecture

The simulation loop runs via `requestAnimationFrame` and is managed by the `useSimulationLoop` hook:

```typescript
function useSimulationLoop() {
  const fixedDt = 1 / 120;  // 120 Hz physics
  const accumulatorRef = useRef(0);
  const lastTimeRef = useRef(0);
  const previousStateRef = useRef<PhysicsState | null>(null);

  const tick = useCallback((timestamp: number) => {
    if (!simulationRunning) {
      lastTimeRef.current = timestamp;
      requestAnimationFrame(tick);
      return;
    }

    const realDelta = (timestamp - lastTimeRef.current) / 1000;  // Convert to seconds
    lastTimeRef.current = timestamp;

    // Clamp realDelta to prevent spiral of death
    const clampedDelta = Math.min(realDelta, 0.1);

    // Accumulate time scaled by simulation speed
    accumulatorRef.current += clampedDelta * simulationSpeed;

    // Fixed timestep physics
    while (accumulatorRef.current >= fixedDt) {
      previousStateRef.current = getState();
      const newState = physicsStep(getState(), fixedDt);
      setState(newState);
      accumulatorRef.current -= fixedDt;
    }

    // Interpolation for smooth rendering
    const alpha = accumulatorRef.current / fixedDt;
    const interpolated = interpolateState(previousStateRef.current, getState(), alpha);
    setRenderState(interpolated);

    requestAnimationFrame(tick);
  }, [simulationSpeed]);

  useEffect(() => {
    requestAnimationFrame(tick);
    return () => cancelAnimationFrame(animationFrameId);
  }, [tick]);
}
```

### 11.2 Physics Step Function

```typescript
function physicsStep(state: PhysicsState, dt: number): PhysicsState {
  // Velocity Verlet integration step 1: half-step velocity
  const force1 = computeGravity(state);
  const accel1 = scale(force1, 1 / state.orbitingBody.mass);
  const halfVelocity = add(state.orbitingBody.velocity, scale(accel1, dt / 2));

  // Step 2: full-step position
  const newPosition = add(state.orbitingBody.position, scale(halfVelocity, dt));

  // Step 3: compute force at new position
  const newStateAtNewPos = { ...state, orbitingBody: { ...state.orbitingBody, position: newPosition } };
  const force2 = computeGravity(newStateAtNewPos);
  const accel2 = scale(force2, 1 / state.orbitingBody.mass);

  // Step 4: full-step velocity
  const newVelocity = add(halfVelocity, scale(accel2, dt / 2));

  // Compute derived quantities
  const derived = computeDerivedQuantities(newPosition, newVelocity, state.centralBody, state.orbitingBody.mass);

  // Update trail
  const newTrail = [...state.trail, newPosition];
  if (newTrail.length > MAX_TRAIL_POINTS) newTrail.shift();

  return {
    ...state,
    orbitingBody: { ...state.orbitingBody, position: newPosition, velocity: newVelocity },
    derived,
    trail: newTrail,
    timeElapsed: state.timeElapsed + dt,
  };
}
```

### 11.3 Simulation Speed Control

The simulation speed multiplier affects the rate at which physics time accumulates, not the physics step size:
- `0.25×`: Slow motion — 1 real second = 0.25 simulation seconds.
- `0.5×`: Half speed.
- `1×`: Real-time — 1 real second = 1 simulation second.
- `2×`: Double speed.
- `4×`: Quadruple speed — useful for observing long-period orbits.

The fixed physics timestep (1/120 s) remains constant; at higher simulation speeds, more physics steps are computed per real-time frame.

### 11.4 Pause and Reset

- **Pause:** The `simulationRunning` flag is set to `false`. The `requestAnimationFrame` loop continues but skips physics computation. The timestamp reference is updated to prevent a large delta when resuming.
- **Reset:** The physics state is restored to the initial conditions defined by the learner's current control settings. The trail is cleared. The time elapsed is reset to 0. Assessment state is preserved (reset does not affect learner progress).

---

## 12. State Management

### 12.1 Store Architecture

Four Zustand stores, each with a clear responsibility boundary:

#### Simulation Store (`simulation-store.ts`)

```typescript
interface SimulationState {
  // Core physics state
  physics: PhysicsState;

  // Initial conditions (for reset)
  initialConditions: {
    distance: number;
    velocityMagnitude: number;
    velocityAngle: number;
    centralBodyMass: number;
    satelliteMass: number;
  };

  // Simulation control
  isRunning: boolean;
  isPaused: boolean;
  simulationSpeed: number;  // 0.25, 0.5, 1, 2, 4
  timeElapsed: number;

  // Actions
  start: () => void;
  pause: () => void;
  reset: () => void;
  setSimulationSpeed: (speed: number) => void;
  setInitialDistance: (d: number) => void;
  setInitialVelocityMagnitude: (v: number) => void;
  setInitialVelocityAngle: (angle: number) => void;
  setCentralBodyMass: (m: number) => void;
  setSatelliteMass: (m: number) => void;
  updatePhysics: (state: PhysicsState) => void;
}
```

#### UI Store (`ui-store.ts`)

```typescript
interface UIState {
  // Phase management (display only; actual logic is in learner-store)
  currentPhase: number;  // 1-4

  // Panel visibility
  sidePanelOpen: boolean;
  activePanel: 'readout' | 'control' | 'phase' | 'feedback';

  // Vector visibility
  showForceVector: boolean;
  showVelocityVector: boolean;
  showTrail: boolean;
  showDistanceMarker: boolean;
  showReferencePlane: boolean;

  // Readout configuration
  readoutFontSize: 'small' | 'medium' | 'large';
  showEnergyReadouts: boolean;

  // Accessibility
  keyboardHelpVisible: boolean;
  screenReaderMode: boolean;

  // Tutorial
  tutorialCompleted: boolean;

  // Actions
  toggleSidePanel: () => void;
  setActivePanel: (panel: string) => void;
  toggleVector: (vector: string) => void;
  setReadoutFontSize: (size: string) => void;
  completeTutorial: () => void;
}
```

#### Learner Store (`learner-store.ts`)

```typescript
interface LearnerState {
  // Current pathway
  pathway: 'standard' | 'accelerated' | 'remedial' | 'misconception-intervention';

  // Phase progress
  completedPhases: number[];
  currentPhaseAttempts: number;
  maxPhaseAttempts: number;

  // Assessment scores
  objectiveScores: {
    o1_inverseSquare: ScoreResult | null;
    o2_orbitalVelocity: ScoreResult | null;
    o3_orbitalParameters: ScoreResult | null;
    o4_energyConservation: ScoreResult | null;
    o5_trajectoryClassification: ScoreResult | null;
    o6_gravitationalField: ScoreResult | null;
  };

  // Prediction history
  predictionHistory: PredictionRecord[];

  // Misconception tracking
  detectedMisconceptions: MisconceptionRecord[];
  misconceptionInterventions: number;

  // Data recording (Phase 2)
  distanceExperimentData: { distance: number; force: number }[];

  // Actions
  recordPrediction: (prediction: PredictionRecord) => void;
  recordMisconception: (misconception: MisconceptionRecord) => void;
  updateObjectiveScore: (objective: string, score: ScoreResult) => void;
  advancePhase: () => void;
  setPathway: (pathway: string) => void;
  recordDistanceData: (entry: { distance: number; force: number }) => void;
}
```

#### Feedback Store (`feedback-store.ts`)

```typescript
interface FeedbackState {
  // Active feedback queue
  activeFeedback: FeedbackItem[];

  // Feedback history (dismissed)
  dismissedFeedback: FeedbackItem[];

  // Actions
  showFeedback: (item: FeedbackItem) => void;
  dismissFeedback: (id: string) => void;
  clearAllFeedback: () => void;
}

interface FeedbackItem {
  id: string;
  type: 'corrective' | 'explanatory' | 'motivational' | 'elaborative' | 'misconception';
  contentKey: string;  // i18n key
  context?: string;    // Additional context for the feedback
  timestamp: number;
}
```

### 12.2 Store Interaction Pattern

```
User Interaction → UI Store action → triggers simulation store action
Simulation loop → physics engine → simulation store update
Simulation store update → triggers derived quantity recomputation
Derived quantities → assessment engine check → learner store update
Learner store update → feedback engine → feedback store update
Feedback store update → UI feedback panel re-render
```

### 12.3 Persistence

The learner store is persisted to `localStorage` via Zustand's `persist` middleware. This enables:
- Session resume (learner can close browser and return to their progress).
- Adaptive pathway continuity (scores and misconception history persist across sessions).

The simulation store is NOT persisted — initial conditions are always fresh on load.

---

## 13. Adaptive Pathway Engine

### 13.1 Pathway Definitions

| Pathway | Condition | Behavior |
|---|---|---|
| **Standard** | Default starting pathway; learner has no history | Full guided experience through all four phases |
| **Accelerated** | Learner correctly predicts inverse-square relationships and trajectory classifications on first attempt in Phases 2 and 3 | Skips redundant guided steps; offers advanced challenges in Phase 3 (e.g., multi-distance comparison, mass variation experiments); extension tasks in Phase 4 |
| **Remedial** | Learner fails a formative assessment trigger | Returns to the relevant concept module with additional scaffolding, more worked examples, optional 2D view, slower simulation speed, smaller sub-questions |
| **Misconception Intervention** | Learner exhibits a specific misconception (detected via misconception probes) | Enters a targeted mini-module that directly confronts the misconception through counter-example simulation; after intervention, learner retries a task requiring corrected understanding; if misconception persists after 2 interventions, flags for human instructor review |

### 13.2 Pathway Routing Logic

The `pathway-engine.ts` module evaluates performance metrics after each assessment trigger and routes accordingly:

```
After each assessment trigger:
  1. Evaluate the learner's response against the trigger's success criteria.
  2. If correct on first attempt AND pathway is Standard:
     - Increment "correctFirstAttempt" counter.
     - If counter >= threshold for accelerated pathway → switch to Accelerated.
  3. If incorrect:
     - Evaluate if the error matches a known misconception.
     - If misconception detected → route to Misconception Intervention pathway.
     - If not a misconception → route to Remedial pathway for the relevant concept.
  4. After completing a remedial or intervention module:
     - Re-present the failed assessment trigger.
     - If still incorrect after 2 retries → flag for human review (in classroom deployment).
```

### 13.3 Remediation Details

When routed to remedial pathway:
- The relevant concept module (C1–C9) is presented with additional scaffolding.
- Visualization is simplified: optional 2D view mode (locks camera to top-down perspective), slower default simulation speed (0.5×), step-by-step trajectory formation (physics advances in discrete steps with learner triggering each step).
- Conceptual prompts are broken into smaller sub-questions.
- Worked examples are provided before the learner retries.
- After completing the remedial module, the learner retries the failed assessment.

### 13.4 Acceleration Details

When routed to accelerated pathway:
- Phase 2: Distance experiment is condensed (3 data points instead of 5; pattern recognition prompt is presented earlier).
- Phase 3: Advanced challenges added:
  - "Can you create an orbit with eccentricity exactly 0.5?"
  - "Find the minimum and maximum distance ratio for a specific eccentricity."
  - "What happens to orbital period when you double the distance? Verify with the readout."
- Phase 4: Extension tasks:
  - Energy conservation quantitative challenge (estimate the speed at periapsis given apoapsis distance).
  - Multi-distance comparison (set up two different orbits and compare their periods).
  - Mass variation experiment (change satellite mass, verify trajectory unchanged).

### 13.5 Performance Metrics

The `performance-tracker.ts` aggregates:
- **Prediction accuracy:** Number of correct predictions / total predictions.
- **First-attempt success rate:** Correct on first try / total tasks attempted.
- **Misconception persistence:** Number of unique misconceptions that persist after 2 interventions.
- **Time-to-mastery per concept:** How quickly the learner masters each concept (not used for routing, but available for analytics).

---

## 14. Formative Assessment System

### 14.1 Assessment Trigger Registry

Each trigger is defined as a data structure in `src/engine/assessment/triggers.ts`:

```typescript
interface AssessmentTrigger {
  id: string;
  phase: 1 | 2 | 3 | 4;
  triggerPoint: string;              // Human-readable description
  type: 'prediction' | 'explanation' | 'classification' | 'proportionality-reasoning' | 'misconception-probe' | 'observation';
  conceptTarget: string;             // C1-C9 concept ID
  objectiveTarget: string;           // O1-O6 objective ID
  successCriteria: SuccessCriteria;
  feedbackKeys: {
    correct: string;                 // i18n key for correct feedback
    incorrect: string;               // i18n key for incorrect feedback
    motivational: string;
  };
  misconceptionMapping?: string[];   // If response indicates these misconceptions, trigger intervention
}
```

### 14.2 Trigger Points (Mapped to Specification §11)

| Trigger ID | Phase | Point | Type | Objective |
|---|---|---|---|---|
| `T1-1` | 1 | After exploration | Observation | O6 (Gravitational Field) |
| `T2-1` | 2 | During distance experiment | Proportionality-reasoning | O1 (Inverse-Square) |
| `T3-1` | 3 | After circular orbit discovery | Explanation | O2 (Orbital Velocity Balance) |
| `T3-2` | 3 | When trajectory changes from circular to elliptical | Prediction | O3 (Orbital Parameters) |
| `T3-3` | 3 | During elliptical orbit observation | Parameter-interpretation | O3 (Orbital Parameters), O4 (Energy Conservation) |
| `T3-4` | 3 | After observing escape trajectory | Classification | O5 (Trajectory Classification) |
| `T4-M` | 4 | Before synthesis | Misconception-probe | All (misconception M3) |
| `T4-1` | 4 | Prediction challenges | Prediction | O3, O5 |
| `T4-2` | 4 | Explanation prompts | Explanation | O2, O4 |
| `T4-3` | 4 | Reflection | Explanation | All |

### 14.3 Prediction Task Implementation

**Flow:**
1. System presents initial conditions (distance, velocity magnitude, velocity direction) in a `PredictionDialog` component.
2. Learner selects from options (for classification predictions) or enters a prediction in structured text.
3. Learner clicks "Run Simulation" to see the actual outcome.
4. The simulation runs, the actual outcome is compared against the prediction.
5. Correct/incorrect feedback is displayed.
6. The prediction result is recorded in the learner store.

**Prediction types:**
- **Trajectory classification:** "Will the orbit be circular, elliptical, or escape?" (multiple choice)
- **Force prediction:** "If we double the distance, what happens to the force?" (multiple choice: "stays same" / "halves" / "quarters" / "doubles")
- **Speed prediction:** "Where will the object be moving fastest — closest to the central body, farthest from it, or the same speed everywhere?" (multiple choice)
- **Parameter prediction:** "If we increase the initial velocity, will the orbit period increase, decrease, or stay the same?" (multiple choice)

### 14.4 Explanation Task Implementation

**Flow:**
1. System presents an `ExplanationPrompt` with a text area and a prompt question.
2. Learner types a free-text explanation.
3. For automated scoring: key phrases are checked against a rubric (e.g., for O2, the explanation should contain "balance" or "equal" and "force" and "acceleration" or "centripetal").
4. For human review scenarios (classroom deployment): explanations are saved for instructor review.

**Scoring approach:** Keyword-based rubric scoring with a confidence threshold. The system checks for presence of key physics terms and correct directional reasoning. This is not natural language understanding — it is pattern matching against expected vocabulary.

### 14.5 Classification Task Implementation

**Flow:**
1. System presents a `ClassificationTask` with three buttons: "Circular," "Elliptical," "Escape."
2. Learner clicks their classification.
3. The system compares against the actual trajectory type (computed by the orbital parameter calculator).
4. Feedback is displayed. If incorrect, the system redirects attention to relevant readouts.

### 14.6 Misconception Probe Implementation

**Flow:**
1. System presents a targeted question from the `MisconceptionProbe` component.
2. The question is drawn from a bank of misconception probes mapped to specific misconceptions (M1–M10 from specification §7).
3. The learner's response is evaluated.
4. If the response indicates a specific misconception, the misconception is recorded in the learner store and a misconception intervention is triggered.

**Misconception detection mapping:**

| Misconception | Probe Question | Detection Pattern |
|---|---|---|
| M2 (no gravity in orbit) | "Why does the orbiting object stay in orbit?" | Response suggesting "no gravity" or "beyond gravity" |
| M3 (mass affects orbit) | "If we double the satellite's mass, what happens to its orbit?" | Response suggesting the orbit changes |
| M4 (constant orbital speed) | "In an elliptical orbit, does the satellite move at the same speed everywhere?" | Response suggesting "yes" or "constant" |
| M5 (bigger orbit = faster) | "Does a satellite in a larger orbit move faster or slower than one in a smaller orbit?" | Response suggesting "faster" |
| M6 (gravity pulls straight) | "Why doesn't the satellite fall straight into the central body?" | Response failing to mention tangential velocity or sideways motion |
| M9 (eccentricity = tilt) | "What does eccentricity measure?" | Response suggesting "tilt" or "inclination" |

---

## 15. Feedback Delivery System

### 15.1 Feedback Content Registry

All feedback content is stored as i18n keys in the locale files (`src/i18n/locales/en.json`). Each feedback item has:
- A unique key.
- The feedback text with placeholders for dynamic values (e.g., `{{distance}}`, `{{force}}`).
- The feedback type (corrective, explanatory, motivational, elaborative, misconception).

### 15.2 Feedback Types and Delivery

| Type | Trigger | Display | Dismissal |
|---|---|---|---|
| **Corrective** | Incorrect prediction/classification | Shown immediately in `FeedbackPanel` as a toast-style notification with redirect-to-observation guidance | Auto-dismiss after 8 seconds or manual dismiss |
| **Explanatory** | Correct conclusion reached | Shown immediately, reinforced with formal principle connection | Manual dismiss (learner reads at their pace) |
| **Motivational** | Successful prediction or productive failure | Shown briefly (3–5 seconds) as a small banner at the top of the screen | Auto-dismiss |
| **Elaborative** | Advanced learner completes task quickly (time threshold: <50% average time) | Shown as an optional "Challenge" card the learner can click to expand | Manual dismiss |
| **Misconception** | Misconception probe activated | Shown as a prominent, centered dialog with counter-example simulation prompt | Requires explicit acknowledgment before dismissal |

### 15.3 Feedback Sequencing

- At most one feedback item is displayed at a time.
- If multiple feedback items are triggered simultaneously (e.g., correct prediction + motivational), they are queued and displayed sequentially.
- The feedback queue is managed in the feedback store.
- Corrective feedback always takes priority in the queue (learners need immediate redirection).

### 15.4 Feedback for Misconception Interventions

When a misconception is detected:
1. The misconception dialog is displayed with the misconception statement and a prompt to "Let's investigate this together."
2. The system enters a mini-module that runs a counter-example simulation (e.g., if the misconception is "mass affects orbit," the system runs the same orbit with different satellite masses side by side).
3. After the counter-example, the system asks the learner to revise their understanding.
4. A new task requiring correct understanding is presented.
5. If the misconception persists after 2 interventions, the system provides a summary and flags for human instructor review.

---

## 16. Accessibility Implementation

### 16.1 Visual Accessibility

**Color vision:**
- All color-coded elements have a secondary distinguishing feature:
  - Force vectors: Red color + standard cone arrowhead + "F" label.
  - Velocity vectors: Blue color + diamond arrowhead + "v" label.
  - Trajectory trail: Color gradient is supplementary; the trail is always visible as a line regardless of color. Speed information can also be read from the speed readout.
- No information is conveyed solely through color. Every color-coded element has a shape, label, or text alternative.

**Contrast:**
- All text meets WCAG AA contrast ratios (4.5:1 for normal text, 3:1 for large text) against background colors.
- Vector elements use high-contrast colors against the dark space background (verified with contrast checking tools during development).
- The reference plane uses a neutral, high-contrast border line in addition to the translucent fill.

**Scale:**
- Readout text is available in three sizes: small (12px), medium (14px), large (18px). Controlled via `FontSizeControl` component.
- The default size is medium. Large size is recommended for classroom projection.

**Animation sensitivity:**
- Simulation speed is controllable from 0.25× to 4× and can be paused at any time.
- No content is conveyed solely through animation timing. All dynamic information is also available through static readouts.

### 16.2 Motor Accessibility

**Keyboard navigation:**
- All interactions are achievable via keyboard:
  - Simulation controls: Space (play/pause), R (reset), [ ] (speed), Arrow keys (rotate view), +/- (zoom).
  - Object placement: Tab to focus control panel, Arrow keys to adjust distance and angle.
  - Velocity adjustment: Tab to velocity controls, Arrow keys to adjust magnitude and direction.
  - Assessment tasks: Tab to buttons/options, Enter/Space to select, Arrow keys to navigate options.
  - Panel navigation: Tab to panel tabs, Arrow keys to switch panels.

**Adjustable input sensitivity:**
- Mouse sensitivity is not a primary concern (orbit controls already support multiple input modes).
- Touch gestures have a configurable dead zone for learners with limited fine motor control.

**One-hand operation:**
- Core simulation controls (play/pause, reset, speed) are accessible with a single hand on the keyboard.
- 3D navigation can be performed with keyboard alone (no mouse required).

### 16.3 Cognitive Accessibility

**Clear language:**
- All prompts, labels, and feedback use plain language at a reading level appropriate for ages 15–20.
- Technical terms (eccentricity, semi-major axis, periapsis) are introduced with brief definitions in tooltips.

**Step-by-step guidance:**
- Complex tasks are broken into numbered steps displayed in the `PhasePanel`.
- Each step requires a single action. The next step is revealed only after the current step is completed.

**Consistent layout:**
- The side panel is always on the right. The 3D canvas always fills the remaining space. The top bar always shows progress.
- Control locations within panels do not change between phases.

**Progress indicator:**
- The top bar shows a four-segment progress indicator (Phase 1–4). Completed phases are highlighted. The current phase is animated. Future phases are dimmed.

### 16.4 Screen Reader Compatibility

**ARIA implementation:**
- The 3D canvas has `role="application"` with `aria-label="Orbital Physics Simulation"`.
- All interactive elements have `aria-label` attributes.
- Readout values use `role="status"` and `aria-live="polite"` for dynamic updates.
- Vector descriptions are available as screen reader-only text (visually hidden) near the orbiting body.

**State announcements:**
- `ScreenReaderAnnouncer` component provides periodic summaries of the simulation state:
  - On simulation start: "Simulation started. Object at distance 3.0 units, velocity 2.1 units per second."
  - On significant state change: "Object approaching central body. Distance decreasing. Force increasing."
  - On phase transition: "Phase 2 complete. Entering Phase 3: Orbital Dynamics."
- Announcements are throttled to avoid overwhelming screen reader users (maximum one announcement per 5 seconds during active simulation).

**Trajectory classification for screen readers:**
- The trajectory classifier component outputs a screen reader announcement whenever the classification changes: "Trajectory type: Elliptical. Eccentricity: 0.45."

### 16.5 Language Accessibility

- All text is externalized via i18next. No text is embedded in images or Three.js scene objects.
- Units are clearly labeled in both visual readouts and screen reader text.
- Number formatting uses locale-appropriate conventions (decimal separator, thousands separator).

### 16.6 Neurodiversity Considerations

- No time pressure: no countdowns, no timed challenges, no time limits on any task.
- Sensory intensity is controllable: simulation speed, visual complexity (toggle vectors, trails, reference plane).
- No flashing or strobing effects in any component.
- The experience can be paused at any time without losing progress.
- Autoplay is never triggered; the learner always explicitly starts the simulation.

---

## 17. Performance & Optimization

### 17.1 Performance Targets

| Metric | Target | Rationale |
|---|---|---|
| Frame rate | ≥ 60 FPS on mid-range hardware (integrated GPU, 2022+) | Smooth vector and trail animation requires consistent frame delivery |
| Physics accuracy | < 0.1% energy drift over 1000 orbits | Orbits must appear stable for educational accuracy |
| Initial load time | < 3 seconds on broadband | Minimize barrier to engagement |
| Memory usage | < 200 MB | Browser tab memory budget for educational applications |
| Input latency | < 50 ms from control change to visual response | Tight feedback loop per §10.3 of specification |

### 17.2 Rendering Optimization

- **Minimal draw calls:** The scene contains approximately 8–10 draw calls total (central body, orbiting body, force vector, velocity vector, trail line, distance marker, reference plane, labels). This is well within GPU budget.
- **No post-processing:** No bloom, SSAO, or other effects that require additional render passes.
- **Geometry optimization:** Sphere geometries use 32×32 segments (sufficient visual quality at typical viewing distances; low polygon count).
- **Trail buffer management:** Circular buffer prevents allocation during simulation. `needsUpdate` flags are set only when the buffer has actually changed.
- **Label rendering:** HTML overlays (via @react-three/drei `Html` component) are positioned via CSS transforms, not re-rendered by Three.js. Updates are batched.

### 17.3 Physics Optimization

- The two-body gravity computation is O(1) per step (single force calculation).
- The Velocity Verlet integrator requires two force evaluations per step (one at current position, one at new position). At 120 Hz physics, this is 240 force evaluations per second — trivial for modern CPUs.
- Orbital parameter computation (Keplerian elements) is also O(1) per step.
- No optimization beyond clean implementation is required for the two-body problem at this scale.

### 17.4 Memory Management

- **Trail buffer:** Pre-allocated at application start. Maximum 2000 Vector3 points × 3 floats × 4 bytes = 24 KB. Negligible.
- **Physics state:** Single state object, replaced (not accumulated) each step. No garbage collection pressure.
- **UI re-renders:** Zustand's selector pattern ensures only components that subscribe to changed state properties re-render. Readout panels subscribe to specific derived values, not the entire simulation state.
- **Texture loading:** Textures are loaded once at application start and cached. No runtime texture loading.
- **No Web Workers needed:** The two-body physics computation is lightweight enough to run on the main thread without impacting frame rate.

### 17.5 Bundle Optimization

- **Code splitting:** The application is split into:
  - Core bundle (physics engine, stores, types): ~30 KB gzipped.
  - 3D scene bundle (Three.js, R3F, scene components): ~150 KB gzipped.
  - UI bundle (React, accessibility components, assessment components): ~50 KB gzipped.
  - Three.js library: ~600 KB gzipped (loaded separately; cached by CDN/browser).
- **Tree shaking:** Vite's Rollup-based production build eliminates unused Three.js modules.
- **Lazy loading:** Phase-specific assessment components and feedback content are lazy-loaded when the relevant phase is reached.

---

## 18. Testing Strategy

### 18.1 Unit Tests

**Scope:** All modules in `src/engine/` and `src/utils/`.

| Module | Test File | Key Tests |
|---|---|---|
| `gravity.ts` | `gravity.test.ts` | Force magnitude correct at known distances; force direction correct; inverse-square relationship verified (force at 2d = F/4, force at 3d = F/9); zero-distance handling (clamped to minimum) |
| `integrator.ts` | `integrator.test.ts` | Circular orbit remains stable over 1000 orbits (energy drift < 0.1%); elliptical orbit preserves shape; position/velocity remain finite |
| `orbital-parameters.ts` | `orbital-parameters.test.ts` | Semi-major axis matches known circular orbit; eccentricity = 0 for circular orbit; period matches Kepler's third law; periapsis < apoapsis for elliptical orbit |
| `energy.ts` | `energy.test.ts` | Total energy conserved in circular orbit (< 0.1% drift); KE + PE = TotalEnergy; energy values correct at known positions |
| `escape-velocity.ts` | `escape-velocity.test.ts` | Escape velocity = √2 × circular speed; escape trajectory has total energy ≥ 0 |
| `triggers.ts` | `triggers.test.ts` | Triggers activate at correct phase and trigger points; success criteria evaluation is correct |
| `predictions.ts` | `predictions.test.ts` | Prediction correctness evaluation; trajectory classification matching |
| `misconceptions.ts` | `misconceptions.test.ts` | Misconception detection patterns correctly identify known misconceptions; false positive rate acceptable |
| `scoring.ts` | `scoring.test.ts` | Mastery thresholds correctly evaluated; partial credit calculation; overall completion criteria |
| `pathway-engine.ts` | `pathway-engine.test.ts` | Standard → Accelerated transition on correct first attempts; Standard → Remedial on failures; Remedial → retry logic; Misconception intervention after 2 failures flags for review |
| `vector-math.ts` | `vector-math.test.ts` | Vector add, subtract, scale, magnitude, normalize, dot product, cross product correctness |

### 18.2 Integration Tests

| Test | Scope | Key Assertions |
|---|---|---|
| `physics-rendering.test.ts` | Physics engine → Simulation Store → Scene component re-render | When physics state updates, the Three.js scene graph elements (position, scale, rotation) update accordingly |
| `assessment-flow.test.ts` | Assessment trigger → scoring → pathway routing → feedback | A failed prediction triggers the correct remedial pathway; a correct prediction advances the learner |
| `phase-transitions.test.ts` | Phase gating logic | Phase 2 is not accessible until Phase 1 mastery criteria are met; Phase 4 mastery gate routes correctly |

### 18.3 End-to-End Tests (Playwright)

| Test | What It Verifies |
|---|---|
| `phase-1-exploration.spec.ts` | Learner can navigate 3D space, observe force vector, respond to observation prompt |
| `phase-2-inverse-square.spec.ts` | Learner completes distance experiment, records data, answers proportionality question |
| `phase-3-orbital-dynamics.spec.ts` | Learner discovers circular orbit, observes elliptical and escape trajectories, reads parameters |
| `phase-4-synthesis.spec.ts` | Learner completes prediction challenges, explanation prompts, and achieves mastery |
| `accessibility.spec.ts` | Full journey completable via keyboard only; ARIA attributes present; screen reader announcements correct |
| `keyboard-navigation.spec.ts` | All interactive elements reachable via Tab; all controls operable via keyboard |

### 18.4 Accessibility Tests

| Test | Tool | Scope |
|---|---|---|
| WCAG compliance | axe-core via Playwright | Automated scan of every page state; must return zero violations for critical/serious issues |
| Screen reader | Playwright + ARIA snapshot testing | Verify that screen reader output matches expected announcements for key interactions |
| Keyboard-only | Playwright | Verify that every interactive element can be reached and operated using only keyboard |
| Color contrast | axe-core | Verify all text meets WCAG AA contrast ratios |
| Focus management | Playwright | Verify focus moves logically through interactive elements; no focus traps |

### 18.5 Physics Accuracy Tests

These are specialized unit tests that verify the physics engine produces physically accurate results:

| Test | Assertion |
|---|---|
| Circular orbit at distance 3 | After 1000 orbits, position variance < 0.01 units, energy drift < 0.1% |
| Elliptical orbit (e=0.5) | Period matches Kepler's third law prediction within 1%; eccentricity preserved to 3 decimal places |
| Escape trajectory | Object distance increases monotonically after escape; total energy > 0 |
| Mass independence | Two orbits with different satellite masses but same initial conditions produce identical trajectories (within floating-point tolerance) |
| Inverse-square verification | Force at distance 2d is exactly F/4 (within floating-point tolerance) |
| Energy conservation | In elliptical orbit, KE is maximum at periapsis and minimum at apoapsis; Total energy is constant |

---

## 19. Deployment & Distribution

### 19.1 Build Process

```bash
# Development
npm run dev          # Vite dev server with HMR (http://localhost:5173)

# Production build
npm run build        # Vite production build → dist/

# Preview production build
npm run preview      # Local preview of production build

# Testing
npm run test         # Vitest unit + integration tests
npm run test:e2e     # Playwright end-to-end tests
npm run test:a11y    # Accessibility tests
npm run lint         # ESLint
npm run typecheck    # TypeScript type checking
```

### 19.2 Deployment Target

**Primary:** Static site deployment to a web server or CDN.

The application is a fully client-side SPA with no server-side requirements. It can be deployed to:
- Static hosting (Netlify, Vercel, GitHub Pages, AWS S3 + CloudFront)
- School Learning Management Systems (LMS) via LTI or iframe embedding
- Local file system (for offline use via a simple HTTP server)

### 19.3 Distribution Formats

| Format | Use Case | Implementation |
|---|---|---|
| Static web app (default) | Browser-based deployment | Vite production build → dist/ folder |
| Offline-capable PWA | Classroom use without reliable internet | Service worker caching of all assets; manifest.json for installability |
| LMS embed | Integration with Canvas, Moodle, etc. | iframe-compatible; no cross-origin issues; passes standard LTI content item |

### 19.4 Browser Compatibility

| Browser | Minimum Version | Notes |
|---|---|---|
| Chrome | 90+ | Primary development target |
| Firefox | 90+ | WebGL 2 support required |
| Safari | 15+ | WebGL 2 support; test touch interactions |
| Edge | 90+ | Chromium-based; same as Chrome |

**No IE11 support.** WebGL 2 is required.

### 19.5 Environment Configuration

```typescript
// vite.config.ts
export default defineConfig({
  define: {
    __APP_VERSION__: JSON.stringify(pkg.version),
  },
  build: {
    target: 'es2020',
    sourcemap: true,  // Source maps for production debugging
    rollupOptions: {
      output: {
        manualChunks: {
          three: ['three'],
          react: ['react', 'react-dom'],
        },
      },
    },
  },
});
```

Environment variables (`.env`):
- `VITE_PHYSICS_SCALE_FACTOR`: Default gravity scaling for simulation units.
- `VITE_MAX_TRAIL_POINTS`: Maximum trail buffer size.
- `VITE_ANALYTICS_ENABLED`: Toggle for learning analytics (if integrated with LMS).

### 19.6 Continuous Integration

```yaml
# .github/workflows/ci.yml (example)
on: [push, pull_request]
jobs:
  quality:
    steps:
      - npm run typecheck
      - npm run lint
      - npm run test
      - npm run test:a11y
  build:
    steps:
      - npm run build
      - Verify dist/ folder size < 5MB total
  e2e:
    steps:
      - npm run test:e2e
```

---

## 20. Builder Instructions

### 20.1 Implementation Order

The Builder MUST implement the application in the following strict sequence. Each phase must be completed and verified before proceeding to the next.

#### Phase A: Foundation (Days 1–3)

1. **Project scaffolding:**
   - Initialize Vite + React + TypeScript project.
   - Install all dependencies from §2.7.
   - Configure ESLint, Prettier, Vitest.
   - Set up project structure from §4.
   - Verify: `npm run dev` starts the dev server and displays a blank page.

2. **Core type definitions:**
   - Implement all interfaces in `src/types/physics.ts`, `src/types/simulation.ts`, `src/types/assessment.ts`, `src/types/pathway.ts`, `src/types/ui.ts`.
   - Implement `src/utils/vector-math.ts` with all Vector3 operations.
   - Verify: All types compile without errors; vector-math unit tests pass.

3. **Configuration files:**
   - Implement `src/config/physics.ts` (G, simulation scale, integration parameters, tolerance thresholds).
   - Implement `src/config/simulation.ts` (default parameter ranges, initial conditions).
   - Implement `src/config/visualization.ts` (vector scale factors, trail colors, camera defaults).
   - Implement `src/config/phases.ts` (phase definitions, transition rules).

4. **Physics engine core:**
   - Implement `src/engine/physics/gravity.ts`.
   - Implement `src/engine/physics/integrator.ts` (Velocity Verlet).
   - Implement `src/engine/physics/energy.ts`.
   - Implement `src/engine/physics/orbital-parameters.ts`.
   - Implement `src/engine/physics/escape-velocity.ts`.
   - Write ALL unit tests from §18.1 for physics modules.
   - Verify: All physics unit tests pass. Physics accuracy tests from §18.5 pass.

#### Phase B: State & Rendering (Days 4–7)

5. **State management:**
   - Implement all four Zustand stores from §12.
   - Implement persistence middleware for learner store.
   - Verify: Stores can be read/written from React components; persistence works across page reloads.

6. **3D Scene — Static elements:**
   - Implement `SimulationScene.tsx` (R3F Canvas wrapper).
   - Implement `CentralBody.tsx` (sphere with texture).
   - Implement `SceneLighting.tsx`.
   - Implement `ReferencePlane.tsx`.
   - Implement `CameraController.tsx` (OrbitControls with keyboard bindings).
   - Verify: 3D scene renders with central body, reference plane, and navigable camera.

7. **3D Scene — Dynamic elements:**
   - Implement `OrbitingBody.tsx` (position bound to simulation store).
   - Implement `ForceVector.tsx` (ArrowHelper, direction and length bound to force state).
   - Implement `VelocityVector.tsx` (distinct arrowhead shape, direction and length bound to velocity state).
   - Implement `DistanceMarker.tsx` (line between bodies with distance label).
   - Verify: Moving the orbiting body in the store updates all scene elements in real time.

8. **Simulation loop:**
   - Implement `src/engine/orchestration/simulation-loop.ts`.
   - Implement `useSimulationLoop` hook.
   - Implement start/pause/reset/speed controls.
   - Verify: Simulation runs, orbiting body moves under gravity, vectors update, readouts display correct values.

9. **Orbital trail:**
   - Implement `OrbitalTrail.tsx` (BufferGeometry Line with color gradient and opacity fade).
   - Implement trail buffer management (circular buffer).
   - Verify: Trail draws correctly during simulation; clears on reset; color encodes speed.

10. **Trajectory classifier:**
    - Implement `TrajectoryClassifier.tsx` (dynamic label based on trajectory type).
    - Verify: Label correctly identifies circular, elliptical, and escape trajectories.

#### Phase C: UI & Interaction (Days 8–12)

11. **App shell and layout:**
    - Implement `AppShell.tsx`, `TopBar.tsx`, `SidePanel.tsx`.
    - Implement phase progress indicator in TopBar.
    - Verify: Layout renders correctly with 3D canvas and side panel.

12. **Readout panel:**
    - Implement `ReadoutPanel.tsx` with all readout values from §9.1.
    - Implement progressive disclosure (phase-based visibility).
    - Verify: Readouts update in real time during simulation; correct values at known test cases.

13. **Control panel:**
    - Implement `ControlPanel.tsx` with all sliders and selectors from §10.
    - Implement `VelocitySlider.tsx`, `DirectionWheel.tsx`, `MassControl.tsx`, `SpeedControl.tsx`.
    - Verify: Adjusting controls changes initial conditions; circular orbit speed displayed on slider.

14. **Simulation controls:**
    - Implement Play/Pause, Reset, Speed +/- buttons.
    - Verify: All controls work correctly; keyboard equivalents function.

#### Phase D: Assessment & Adaptive System (Days 13–17)

15. **Assessment engine:**
    - Implement `src/engine/assessment/triggers.ts` with all triggers from §14.2.
    - Implement `src/engine/assessment/predictions.ts`.
    - Implement `src/engine/assessment/scoring.ts`.
    - Implement `src/engine/assessment/misconceptions.ts`.
    - Write ALL unit tests from §18.1 for assessment modules.
    - Verify: All assessment unit tests pass.

16. **Assessment UI components:**
    - Implement `PredictionDialog.tsx`, `ExplanationPrompt.tsx`, `ClassificationTask.tsx`, `MisconceptionProbe.tsx`, `MasteryGate.tsx`.
    - Verify: Each component renders correctly and records responses to the learner store.

17. **Adaptive pathway engine:**
    - Implement `src/engine/adaptive/pathway-engine.ts`.
    - Implement `src/engine/adaptive/performance-tracker.ts`.
    - Write ALL unit tests from §18.1 for adaptive modules.
    - Verify: Pathway routing works correctly for all four pathways.

18. **Phase content:**
    - Implement PhasePanel content for all four phases (instructions, prompts, tasks).
    - Implement data recording table for Phase 2.
    - Verify: Each phase's content renders correctly; transitions between phases work.

#### Phase E: Feedback & Accessibility (Days 18–21)

19. **Feedback system:**
    - Implement `src/engine/feedback/feedback-store.ts` and `delivery.ts`.
    - Implement `FeedbackPanel.tsx`.
    - Implement all feedback types from §15.2.
    - Verify: Correct feedback is displayed for correct/incorrect responses; feedback sequencing works.

20. **Accessibility implementation:**
    - Implement `ScreenReaderAnnouncer.tsx` with ARIA live regions.
    - Implement `KeyboardHelp.tsx` overlay.
    - Implement `FontSizeControl.tsx`.
    - Add ARIA labels to all interactive elements.
    - Add screen reader descriptions for vectors and simulation state.
    - Implement keyboard navigation for all interactions.
    - Verify: Full journey completable via keyboard only; axe-core passes with zero critical/serious violations.

21. **Localization foundation:**
    - Initialize i18next with English locale.
    - Externalize all UI text, prompts, feedback, and error messages.
    - Verify: Application renders correctly with externalized text.

#### Phase F: Polish & Testing (Days 22–25)

22. **Tutorial overlay:**
    - Implement Phase 1 tutorial that teaches 3D navigation controls.
    - Make tutorial skippable (localStorage flag).
    - Verify: Tutorial plays through correctly; skip works.

23. **Performance optimization:**
    - Profile rendering frame rate; optimize if below 60 FPS target.
    - Verify physics accuracy tests pass (§18.5).
    - Optimize bundle size.
    - Verify: Frame rate ≥ 60 FPS on target hardware; bundle < 5 MB.

24. **E2E testing:**
    - Write and run all Playwright tests from §18.3.
    - Verify: All E2E tests pass.

25. **Final accessibility audit:**
    - Run axe-core scans on every interactive state.
    - Manual screen reader testing with NVDA/VoiceOver.
    - Manual keyboard-only testing.
    - Verify: Zero critical/serious accessibility violations.

### 20.2 Critical Constraints for the Builder

1. **DO NOT modify educational content.** All prompts, feedback messages, assessment questions, and misconception probes must match the specification exactly. The text content is defined in the AI Focus Specification and will be provided separately as i18n strings.

2. **DO NOT skip accessibility.** The specification explicitly requires keyboard navigation, screen reader compatibility, color vision accessibility, and motor accessibility. These are not optional features.

3. **DO NOT use Euler integration.** The Velocity Verlet integrator is specified for a critical reason: Euler integration will cause orbits to spiral and become unstable, which would undermine the educational objectives. If there is any doubt, run the physics accuracy tests from §18.5.

4. **DO NOT add features outside the specification scope.** The specification explicitly excludes three-body problems, relativistic effects, drag, tidal forces, and other advanced phenomena. Adding these would confuse the educational experience.

5. **DO implement the color-encoding for the trajectory trail.** The specification requires color-coded speed visualization on the trail. This is a key visualization feature for Objective 4 (Energy Conservation).

6. **DO implement the distinct arrowhead shapes for force and velocity vectors.** This is a critical accessibility requirement. Color alone is not sufficient.

7. **DO implement progressive disclosure of readouts.** Readouts must appear gradually across phases, not all at once. This is a core cognitive load management strategy.

8. **DO implement the circular orbit speed reference on the velocity slider.** The slider must display the velocity as a multiplier of circular orbit speed (e.g., "1.0× circular speed"). This makes the educational relationship between velocity and trajectory type immediately visible.

9. **DO test physics accuracy.** Run the physics accuracy tests (§18.5) after implementing the physics engine. Stable orbits over 1000 revolutions is a hard requirement.

10. **DO persist learner progress.** The learner store must persist to localStorage so that returning learners resume their progress and adaptive pathway state.

### 20.3 Verification Checklist

Before marking any implementation phase as complete, the Builder must verify:

| Phase | Verification |
|---|---|
| A (Foundation) | All physics unit tests pass; all physics accuracy tests pass |
| B (State & Rendering) | Scene renders correctly; simulation runs; vectors update; trail draws; trajectory classifier works |
| C (UI & Interaction) | All controls function; readouts display correctly; layout is responsive |
| D (Assessment) | All assessment tests pass; pathway routing works for all four pathways |
| E (Accessibility) | Keyboard-only journey works; axe-core passes; screen reader announcements correct |
| F (Polish) | E2E tests pass; frame rate target met; bundle size within limits |

### 20.4 Known Pitfalls

| Pitfall | Prevention |
|---|---|
| Euler integration causing orbital decay | Use Velocity Verlet exclusively; verify with accuracy tests |
| Force/velocity vectors becoming invisible at large distances | Implement clamping (min/max arrow length) in visualization config |
| Trail buffer memory leak | Use circular buffer with pre-allocated geometry; never append to array without trimming |
| Screen reader not announcing dynamic readouts | Use `aria-live="polite"` on readout containers; throttle announcements |
| Readout panel re-rendering on every frame causing performance issues | Use Zustand selectors to subscribe only to specific derived values; memoize components |
| Three.js scene not updating when store changes | Ensure R3F components properly subscribe to Zustand store via `useStore` hooks |
| Touch gestures conflicting with 3D navigation | Configure OrbitControls touch actions; test on mobile devices |

---

*End of Architecture Blueprint.*
