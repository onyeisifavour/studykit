# Agent 4: Pedagogical Sequence Builder — Blueprint

## 1. Overview

Agent 4 orders the selected questions from Agent 3 into a psychologically and
pedagogically sound sequence for the quiz. It does **not** select questions,
alter question text, or modify answer keys. It purely determines presentation
order to maximize student engagement, prevent early frustration, and build
diagnostic confidence.

Agent 4 is the **first point where the quiz becomes a readable experience** —
before this, the quiz is just a bag of questions.

---

## 2. Inputs

| Input | Source | Format |
|-------|--------|--------|
| Selected Items Manifest | Agent 3 | JSON — selected questions with full text, type, topic, source (bank/sim), objective_type, rationale |
| Diagnostic Priority Profile | Background models (from chat) | Free-form research reports (prerequisite severity, memorization flags, anxiety/stability notes) |
| User preferences | Settings + chat | Section prefs (MCQ/Hybrid/Theory × sim/non-sim), question count, style constraints |

### Sample selected item (from Agent 3)
```json
{
  "slot_number": 3,
  "selected_question": {
    "text": "2(x + 3) = 10. Solve for x.",
    "type": "MCQ",
    "subject": "Mathematics",
    "topic": "Distributive Property",
    "format": "Non-Sim",
    "options": ["x = 2", "x = 4", "x = 7", "x = 8"],
    "correct_answer": "x = 2"
  },
  "objective_type": "prerequisite_repair",
  "source": "bank",
  "match_confidence": "high",
  "selection_rationale": "Option B traps partial distribution error"
}
```

### Sample sim selected item
```json
{
  "slot_number": 6,
  "selected_question": {
    "text": "Now change velocity to 30 m/s. Record the range.",
    "type": "Hybrid",
    "subject": "Physics",
    "topic": "Projectile Motion",
    "format": "Sim",
    "sim_name": "projectile_motion",
    "sim_set": 1,
    "sim_instruction": "Set launch angle to 45°, velocity to 20 m/s. Run and record.",
    "correct_answer": "91.8 metres"
  },
  "objective_type": "transfer_mechanism",
  "source": "sim_generated",
  "match_confidence": "high",
  "selection_rationale": "Generated sim question tests parameter-variation transfer"
}
```

---

## 3. Step-by-Step Process

```
[Selected Items + Diagnostic Profile + User Preferences]
                          │
                          ▼
       1. Cognitive Arc & Pacing Curve Mapping (SUBAGENT 4a)
                          │
                          ▼
       2. Slot Sorting & Sequencing Rules (CODE)
                          │
                          ▼
       3. Context-Switching Optimization (CODE)
                          │
                          ▼
       4. Final Sequenced Quiz Manifest Generation (CODE)
                          │
                          ▼
                    [To Agent 5]
```

---

## 4. Step Details

### Step 1: Cognitive Arc & Pacing Curve Mapping (Subagent 4a)

**Task:** Read the diagnostic profile and choose the pacing arc template that
best fits the student's knowledge state.

**Input:**
- Diagnostic priority profile summary (from background reports):
  - Are there high-severity prerequisite flaws?
  - Is the student relying on memorized formulas?
  - Overall foundational stability notes
- Question count

**Process — choose one arc template:**

| Arc | When to use | Stage flow |
|-----|-------------|-----------|
| **Repair First** | High prerequisite flaws / unstable foundation | Warm-up → Prerequisite Repair → Core Concept Gaps → Transfer / Elevation → User Preference Finale |
| **Ramp Up** | High formula memorization, stable foundation | Standard Procedural Drill → Mechanism / Transfer Check → Prerequisite Polish → Synthesis |
| **Balanced** | Mixed profile, no dominant issue | Warm-up → Targeted Gaps → Challenge → Elevation |

**Output (JSON):**
```json
{
  "pacing_strategy": "Repair First Arc",
  "target_cognitive_flow": "Confidence Anchor → Prerequisite Fix → Core Misconception → Transfer → Elevation",
  "stage_sequence": [
    { "stage": "warm_up", "position_range": [1, 1] },
    { "stage": "prerequisite_repair", "position_range": [2, 4] },
    { "stage": "core_concept_gap", "position_range": [5, 7] },
    { "stage": "transfer_elevation", "position_range": [8, 9] },
    { "stage": "user_preference_finale", "position_range": [10, 10] }
  ],
  "rationale": "High-severity prerequisite flaws on Distributive Property require foundational repair before testing Quadratics."
}
```

**Note:** position_range values are **targets**, not hard rules. The code
re-balances if the counts don't line up (e.g. 4 prerequisite items but only
3 prerequisite positions → spill into stage start).

---

### Step 2: Slot Sorting & Sequencing Rules (Code)

**Task:** Place each selected item into the ordering determined by the pacing
arc, using `objective_type` as the stage driver.

**Stage → objective_type mapping:**

| Pacing Stage | Matches objective_type |
|--------------|----------------------|
| Warm-up / Confidence Anchor | First item, chosen for approachability (shortest text, MCQ if available, non-sim) |
| Prerequisite Repair | `prerequisite_repair` |
| Core Concept Gap | `conceptual_gap` |
| Transfer / Elevation | `transfer_mechanism` then `synthesis_elevation` |
| User Preference Finale | Items matching user's explicit style request (e.g. `style_constraint: calculation`), placed last |

**Approachability scoring for the Gateway (position 1):**
- Prefer MCQ over Hybrid over Theory (MCQ is fastest to engage with)
- Prefer shorter question text
- Prefer non-sim over sim (sim requires setup effort)
- Prefer `conceptual_gap` or low-severity items over `prerequisite_repair` with
  high-severity traps (avoid triggering the student's known failure on Q1)

**Sorting algorithm (code):**
1. Bucket items by objective_type → stage
2. Within each stage bucket, keep Agent 3's `match_confidence` order
   (high confidence first)
3. Concatenate buckets in arc stage order
4. Select the Gateway as the single most approachable item across ALL buckets
   and move it to position 1 (swap, don't duplicate)

---

### Step 3: Context-Switching Optimization (Code)

**Task:** Minimize jarring topic jumps by grouping consecutive items that share
a topic, **without** breaking the stage order.

**Rules:**
1. Process stages left to right (warm-up → finale)
2. Within each stage, group items by `subject` then `topic`
   (e.g. both Distributive Property items stay adjacent)
3. If two adjacent stages have items from the same topic, allow them to merge
   across the stage boundary ONLY if the pacing arc still reads coherently
   (e.g. a Prerequisite Repair on Distributive Property followed immediately
   by a Core Concept Gap on the same topic is good; the reverse is not)
4. Sim questions in the same `sim_set` MUST remain consecutive
   — never split a sim set across unrelated questions

**Output:** ordered list of items with adjusted positions.

---

### Step 4: Final Sequenced Quiz Manifest Generation (Code)

**Task:** Assign final `sequence_index`, `pacing_stage`, and
`position_rationale` to every item, then format as the output schema.

**Position rationale templates:**
- Gateway: `"Most approachable item — anchors confidence and establishes baseline."`
- Stage item: `"{objective_type} on {topic} — placed in {stage} per {pacing_strategy}."`
- Sim set: `"Kept consecutive with SimSet {sim_set} to preserve shared setup."`
- User finale: `"Matches user request for {style_constraint} — placed as finale."`

**Output:**
```json
{
  "sequence_metadata": {
    "total_questions": 10,
    "pacing_strategy": "Repair First Arc",
    "target_cognitive_flow": "Confidence Anchor → Prerequisite Fix → Core Misconception → Transfer → Elevation"
  },
  "ordered_quiz_sequence": [
    {
      "sequence_index": 1,
      "question": {
        "text": "What is the pH of pure water?",
        "type": "MCQ",
        "subject": "Chemistry",
        "topic": "Acids",
        "format": "Non-Sim",
        "options": ["3", "7", "11", "14"],
        "correct_answer": "7"
      },
      "objective_type": "conceptual_gap",
      "source": "bank",
      "pacing_stage": "Warm-up / Confidence Anchor",
      "position_rationale": "Most approachable item — anchors confidence and establishes baseline."
    },
    {
      "sequence_index": 2,
      "question": {
        "text": "2(x + 3) = 10. Solve for x.",
        "type": "MCQ",
        "subject": "Mathematics",
        "topic": "Distributive Property",
        "format": "Non-Sim",
        "options": ["x = 2", "x = 4", "x = 7", "x = 8"],
        "correct_answer": "x = 2"
      },
      "objective_type": "prerequisite_repair",
      "source": "bank",
      "pacing_stage": "Prerequisite Repair",
      "position_rationale": "prerequisite_repair on Distributive Property — placed early per Repair First Arc."
    },
    {
      "sequence_index": 6,
      "question": {
        "text": "Now change velocity to 30 m/s. Record the range.",
        "type": "Hybrid",
        "subject": "Physics",
        "topic": "Projectile Motion",
        "format": "Sim",
        "sim_name": "projectile_motion",
        "sim_set": 1,
        "sim_instruction": "Set launch angle to 45°, velocity to 20 m/s. Run and record.",
        "correct_answer": "91.8 metres"
      },
      "objective_type": "transfer_mechanism",
      "source": "sim_generated",
      "pacing_stage": "Transfer / Elevation",
      "position_rationale": "Kept consecutive with SimSet 1 to preserve shared setup."
    }
  ]
}
```

**Sim metadata note:** every sim question keeps `sim_name`, `sim_set`,
`sim_instruction` through to the quiz UI. The instruction travels with the
question wherever it lands.

---

## 5. Subagent Assignment

| Step | Name | AI Needed? | Verdict |
|------|------|-----------|---------|
| 1 | Cognitive Arc & Pacing Curve Mapping | ✅ Reads diagnostic profile, chooses arc — needs judgment | **Subagent 4a** |
| 2 | Slot Sorting & Sequencing Rules | ❌ Deterministic bucket-and-sort by objective_type | **Code** |
| 3 | Context-Switching Optimization | ❌ Group-by-topic, keep sim sets consecutive | **Code** |
| 4 | Final Sequenced Quiz Manifest Generation | ❌ JSON assembly with rationale templates | **Code** |

**Total: 1 subagent** (4a)

---

## 6. Data Flow Diagram

```
                     ┌──────────────────────┐
                     │ Agent 3 Selected Items│
                     │ Manifest              │
                     └──────────┬───────────┘
                                │
                                ▼
              ┌──────────────────────────────┐
              │  STEP 1: SUBAGENT 4a         │
              │  Cognitive Arc & Pacing      │
              │  Curve Mapping               │
              │  (diagnostic profile → arc)  │
              └──────────┬───────────────────┘
                         │
                         ▼
              ┌──────────────────────────────┐
              │  STEP 2: CODE                │
              │  Bucket by objective_type,   │
              │  order stages, pick Gateway  │
              └──────────┬───────────────────┘
                         │
                         ▼
              ┌──────────────────────────────┐
              │  STEP 3: CODE                │
              │  Group topics, keep          │
              │  sim sets consecutive        │
              └──────────┬───────────────────┘
                         │
                         ▼
              ┌──────────────────────────────┐
              │  STEP 4: CODE                │
              │  Sequenced Quiz Manifest     │
              └──────────┬───────────────────┘
                         │
                         ▼
              ┌──────────────────────────────┐
              │  To Agent 5                  │
              │  (Compliance Auditor)        │
              └──────────────────────────────┘
```

---

## 7. Edge Cases

| Scenario | Handling |
|----------|----------|
| More prerequisite items than prerequisite positions | Spill into the next stage's start; keep arc order intact |
| All items are the same objective_type | Bucket-sort within single stage; Gateway = most approachable; order by match_confidence |
| Sim questions from same set split by other items | Code forces them consecutive (Rule 4) — overrides topic grouping |
| User style constraint but no items match it | Skip finale stage; arc ends at Elevation; note omission in rationale |
| Only 1-2 questions total | Arc collapses: Gateway + single stage; no artificial staging |
| Same topic spans two stages | Merge across boundary if arc reads coherently (prerequisite → core same-topic is OK) |
| Duplicate question text appears twice | Drop the duplicate (Agent 5 also verifies) |

---

## 8. Open Questions

- [ ] Should the subagent 4a receive the full diagnostic reports or a condensed
      priority summary? (Condensed reduces tokens; full increases accuracy)
- [ ] Is the user-preference finale a separate stage or folded into Elevation?
- [ ] Should Gateway selection prefer sim questions ever, or always non-sim?
      (Sim adds setup friction — likely always non-sim)
- [ ] Does the quiz UI need `pacing_stage` labels, or is it internal metadata only?
