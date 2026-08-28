# Simulation Workflow Blueprint

## 1. Overview

The simulation workflow handles quiz questions that require running a simulation
(like a physics lab) to collect measurements and answer questions. Unlike non-sim
questions which are selected from the question bank, sim questions are **generated
on-the-fly** by AI based on simulation README files.

The sim workflow runs alongside the non-sim pipeline and converges at **Agent 3**
(Candidate Evaluator), which picks questions from both pools.

---

## 2. Architecture

```
              PRE-QUIZ CHAT
                    │
                    ▼
    ┌───────────────┴───────────────────┐
    │                                   │
    ▼                                   ▼
AGENT 1 (Quota Planner)       S1 (Sim Analyzer × N READMEs)
    │                                   │
    └───────────────┬───────────────────┘
                    ▼
        S2 (Sim Placement Model)
                    │
                    ▼
        S3 (Sim Question Generator)
                    │
                    ▼
    AGENT 3 (Candidate Evaluator)
    │  ┌── bank pool (non-sim)  ──┐
    │  └── sim questions (from S3)─┘
    │  Picks best per slot
    ▼
AGENT 4 (Sequence Builder)
    ▼
AGENT 5 (Compliance Auditor)
    ▼
        QUIZ
```

---

## 3. Agent S1: Sim Analyzer

### Purpose
Evaluate one simulation README against the 4 background model reports and
produce fit scores indicating how useful the sim is for addressing each flaw
type.

### Input (per call)
- One simulation README (parameters, controls, outputs)
- All 4 background model reports (knowledge-graph, misconception,
  mechanism, drill-recommender)

### Output (per call)
```
{
  "sim_name": "projectile_motion",
  "fit_scores": {
    "prerequisite_flaw": {
      "score": 9,
      "rationale": "Requires velocity decomposition — addresses vector component flaw"
    },
    "conceptual_gap": {
      "score": 6,
      "rationale": "Tests range-angle relationship, moderate conceptual depth"
    },
    "memorized_state": {
      "score": 3,
      "rationale": "Formula recall with varying params, not strong transfer test"
    },
    "mastered_state": {
      "score": 8,
      "rationale": "Multi-variable synthesis with real measurement noise"
    }
  },
  "recommended_type": "Hybrid",
  "recommended_section": "A"
}
```

### Execution
- Runs in **parallel** with Agent 1
- One subagent call per README (separate instances, no cross-context)
- Total = N parallel calls (one per simulation)

### Subagents
**1 subagent** — `sim_analyzer`
- Subagent prompt: `sim_s1_analyzer.md`

---

## 4. Agent S2: Sim Placement Model

### Purpose
Take all S1 analysis reports + Agent 1's quota + user preferences and decide
which sims to include, which flaw they address, and which section they go in.

### Inputs
- All S1 analysis reports (N JSON objects)
- Agent 1's quota manifest (prerequisite=4, conceptual=3, etc.)
- User preferences (MCQ☐/Hybrid☐/Theory☐ with sim enabled per type)

### Process

```
1. Filter out sims whose recommended_type is disabled by user prefs
2. For each sim, calculate weighted score per flaw:
       weighted_score = fit_score × flaw_priority_weight
   where flaw_priority_weight is highest for prerequisite (1.0)
   down to mastered (0.4)
3. Rank sim-flaw pairs by weighted score
4. Allocate from highest priority flaw down:
   - For each unfilled quota slot, assign the best-ranked
     sim that addresses that flaw
   - A single sim can fill multiple slots if it addresses
     multiple flaws at high scores
5. If tight quota: only include sims where fit_score ≥ 7
   (skip sims where a bank question would be better)
```

### Output
```json
{
  "sim_placements": [
    {
      "sim_name": "projectile_motion",
      "assigned_flaw": "prerequisite_flaw",
      "slots": 1,
      "section_type": "Hybrid",
      "fit_score": 9
    },
    {
      "sim_name": "circuit_lab",
      "assigned_flaw": "conceptual_gap",
      "slots": 1,
      "section_type": "MCQ",
      "fit_score": 8
    }
  ]
}
```

### Execution
- Runs **after** Agent 1 + all S1 calls complete
- Single subagent call

### Subagents
**1 subagent** — `sim_placement_model`
- Subagent prompt: `sim_s2_placement.md`

**Code step** (S2b): Apply user section preferences as a pre-filter before
passing to the subagent.

---

## 5. Agent S3: Sim Question Generator

### Purpose
Generate actual simulation questions that function where they "fit" —
testing the specific flaw each sim was assigned to.

### Inputs
- S2 placement decisions (which sims, which flaws, which sections)
- Simulation READMEs for the selected sims

### Output
One `{Set N}[...]` block per assigned sim. Each block has a single shared
`instruction`, an ordered list of questions, and paired answers:

```
{Set 1}[
{instruction}[Set launch angle to 45°, velocity to 20 m/s. Run and record.]
{questions}[
Q1: What is the maximum height reached? [Type: Hybrid; Subject: Physics; Topic: Projectile Motion; Format: Sim]
Q2: Which angle gives the maximum range? [Type: MCQ; Subject: Physics; Topic: Projectile Motion; Format: Sim]
A. 30°
B. 45°
C. 60°
D. 75°
]
{answers}[
A1: 10.2 metres [Type: Hybrid]
A2: 45° [Type: MCQ]
]]
```

### Answer bank format
Answers are stored per question inside the set's `{answers}[...]` block,
tagged with only the Type. MCQ answers store the **full option text** (not letter):

```
A1: 10.2 metres [Type: Hybrid]
A2: 45° [Type: MCQ]
```

### Instruction Model
- A SimSet has exactly **one shared instruction** — the base simulation setup
  the student performs before answering (e.g. "Set launch angle to 45°…").
- If an individual question needs different parameters, that change is stated
  **in the question's own text** (e.g. "Now change velocity to 30 m/s. Record
  the range."). The base instruction is not duplicated or overridden.
- The instruction is displayed above **every** sim question in the set,
  regardless of where that question lands in the quiz.
- This makes shuffling safe: each sim question is self-contained (base
  instruction + optional in-text parameter change), so a question retains its
  setup wherever it appears.

### Execution
- Runs **after** S2 completes
- Single subagent call

### Subagents
**1 subagent** — `sim_question_generator`
- Subagent prompt: `sim_s3_generator.md`

---

## 6. Convergence at Agent 3

Agent 3 (Candidate Evaluator) receives **two pools** of candidates:

| Pool | Source | Format | Selection method |
|------|--------|--------|-----------------|
| Non-sim | Agent 2 (bank search) | Tagged questions with [Format: Non-Sim] | Text matching against diagnostic reports |
| Sim | S3 (generated) | Tagged questions with [Format: Sim] | Text matching against diagnostic reports |

Agent 3 treats both pools equally. It assigns the best-fitting question from
either pool to each slot, checking:
- Does this question test the assigned flaw?
- Does its Type match the slot's requirement?
- Does its difficulty match the diagnostic profile?

---

## 7. Execution Timeline

```
TIME ──────────────────────────────────────────────────────►

Agent 1 ─────────────────────────────────►
S1 (×N READMEs) ─────────────────────────► (parallel)
                                              │
                                              ▼
                                    S2 ──────► (needs A1 + all S1 done)
                                              │
                                              ▼
                                    S3 ──────►
                                              │
                                              ▼
                    Agent 2 ────────►
                                              │
                                              ▼
                                    Agent 3 ──► (convergence)
                                              │
                                              ▼
                                    Agent 4 ──►
                                              │
                                              ▼
                                    Agent 5 ──►
                                              │
                                              ▼
                                         QUIZ UI
```

---

## 8. Dependencies

| Step | Depends On | Blocks |
|------|-----------|--------|
| Agent 1 | 4 bg reports + user request | Agent 2, S2 |
| S1 (×N) | 4 bg reports + READMEs | S2 |
| Agent 2 | Agent 1 | Agent 3 |
| S2 | Agent 1 + all S1 | S3 |
| S3 | S2 | Agent 3 |
| Agent 3 | Agent 2 + S3 | Agent 4 |
| Agent 4 | Agent 3 | Agent 5 |
| Agent 5 | Agent 4 | Quiz UI |

---

## 9. Open Questions

- [ ] S2 threshold: what minimum fit_score warrants inclusion?
- [ ] S2: how to split the difference when two sims address the same flaw?
- [ ] S3: can sim questions include multi-step Theory (sub-parts) or only MCQ/Hybrid?
- [ ] S3: should generated sim questions carry simulation-specific metadata
      (parameter values, expected measurement ranges)?
- [ ] Convergence: should Agent 3 prefer sim over bank if scores are equal?
