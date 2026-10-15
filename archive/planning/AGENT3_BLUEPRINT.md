# Agent 3: Candidate Evaluator & Selector — Blueprint

## 1. Overview

Agent 3 is the **convergence point** where non-sim and sim workflows meet. It receives candidate questions from two sources and selects the best-fitting question for each slot.

This agent does **not generate** any questions — it only picks from existing candidates.

---

## 2. Inputs

| Input | Source | Format |
|-------|--------|--------|
| Slot allocations | Agent 1 | JSON manifest (slot_number, objective_type, topic, target_issue) |
| Non-sim candidate pool | Agent 2 | JSON query specs + actual question texts filtered from bank |
| Sim candidate pool | S3 | Tagged questions with [Format: Sim] |
| Diagnostic reports | Background models (from chat) | Free-form research reports |

---

## 3. Step-by-Step Process

```
[Slot Manifest + Bank Pool + Sim Pool + Diagnostic Reports]
                          │
                          ▼
       1. Candidate Pool Matching & Grouping (CODE)
                          │
                          ▼
       2. Semantic Fit & Distractor Alignment (SUBAGENT 3b)
                          │
                          ▼
       3. Fallback Triggering (CODE)
                          │
                          ▼
       4. Selected Items Manifest Generation (CODE)
                          │
                          ▼
                    [To Agent 4]
```

---

## 4. Step Details

### Step 1: Candidate Pool Matching & Grouping (Code)

**Task:** For each slot in the manifest, gather all candidate questions from both pools (non-sim + sim) that match the slot's `topic` and `objective_type`.

**Logic:**
```
For each slot:
  1. Find all non-sim candidates where topic matches slot.topic
     (and Type matches if slot has a specific type requirement)
  2. Find all sim candidates where topic matches slot.topic
     (and assigned_flaw matches slot.objective_type)
  3. Merge into a single candidate list for this slot
  4. If pool is empty → mark for fallback (Step 3)
```

**Output:** `{slot_number: [candidate_question, ...]}`

---

### Step 2: Semantic Fit & Distractor Alignment (Subagent 3b)

**Task:** For each slot with multiple candidates, read the actual question texts and compare them against the diagnostic reports to pick the best match.

**Input per slot:**
```
Slot 1: prerequisite_repair, topic="Distributive Property", target_issue="Partial Distribution Error"
Diagnostic notes: "Student consistently distributes to first term only"

Candidates:
  1. "2(x + 3) = 10. Solve for x." [Type: MCQ; Subject: Mathematics; Topic: Distributive Property]
     A. x = 2
     B. x = 4    ← traps partial distribution (2x + 3 = 10 → x = 7/2, not listed!)
     C. x = 7
     D. x = 8

  2. "3(y - 2) = 15. Solve for y." [Type: Hybrid; Subject: Mathematics; Topic: Distributive Property]
     (No options — show working)
```

**Candidate selection logic:**
- **Distractor alignment:** Does a MCQ option specifically trap the exact error the student made?
- **Depth check:** If student's understanding is memorized (from mechanism-evaluator), prefer questions that require conceptual explanation over plug-and-chug.
- **Type match:** Prefer candidates whose Type (MCQ/Hybrid/Theory) matches the slot's natural fit.

**Output per slot:** Selected question_id + confidence score + rationale

---

### Step 3: Fallback Triggering (Code)

**Task:** If a slot has zero candidates (pool is empty), trigger fallback resolution.

**Fallback tiers (from Agent 2's query specs):**
```
Tier 1 (exact):   topic exact match + type exact match
Tier 2 (topic):   parent topic + type exact match
Tier 3 (type):    parent topic + ANY type
```

For sim candidates, fallback means expanding to different flaw assignments or different section types.

**Output:** If all tiers fail → `"status": "MISSING_BANK_ITEM"` flagged to Agent 5.

---

### Step 4: Selected Items Manifest Generation (Code)

**Task:** Format selections into the standard output schema.

**Output:**
```json
{
  "selection_summary": {
    "total_slots": 10,
    "successful_matches": 9,
    "fallback_used_count": 1,
    "missing_count": 0
  },
  "selected_items": [
    {
      "slot_number": 1,
      "selected_question": {
        "text": "2(x + 3) = 10. Solve for x.",
        "type": "MCQ",
        "subject": "Mathematics",
        "topic": "Distributive Property",
        "format": "Non-Sim",
        "options": ["x = 2", "x = 4", "x = 7", "x = 8"],
        "correct_answer": "x = 2",
        "answer_text": "x = 2"
      },
      "source": "bank",
      "match_confidence": "high",
      "selection_rationale": "Option B (x = 4) specifically traps partial distribution error — matches student's exact misconception"
    },
    {
      "slot_number": 5,
      "selected_question": {
        "text": "Set the launch angle to 45°, velocity to 20 m/s. Record the maximum height.",
        "type": "Hybrid",
        "subject": "Physics",
        "topic": "Projectile Motion",
        "format": "Sim",
        "sim_name": "projectile_motion",
        "sim_instruction": "Set launch angle to 45°, velocity to 20 m/s. Run and record.",
        "correct_answer": "10.2 metres"
      },
      "source": "sim_generated",
      "match_confidence": "high",
      "selection_rationale": "Generated sim question directly targets prerequisite velocity decomposition flaw"
    }
  ],
  "missing_items": []
}
```

**Sim metadata note:** every sim question keeps its `sim_name`, `sim_set`, and
`sim_instruction` fields through Agent 3 → Agent 4 → Agent 5. The instruction
(shared per SimSet, with any per-question parameter change stated in the
question text) travels with the question, so the quiz UI can always show the
setup box regardless of the question's final position.

---

## 5. Subagent Assignment

| Step | Name | AI Needed? | Verdict |
|------|------|-----------|---------|
| 1 | Candidate Pool Matching & Grouping | ❌ Just group by slot_number + topic match | **Code** |
| 2 | Semantic Fit & Distractor Alignment | ✅ Reads question text, compares against diagnostic reports, applies judgment | **Subagent 3b** |
| 3 | Fallback Triggering | ❌ If-else logic through pre-defined tiers | **Code** |
| 4 | Selected Items Manifest Generation | ❌ JSON assembly | **Code** |

**Total: 1 subagent** (3b)

---

## 6. Data Flow Diagram

```
                    ┌──────────────────────┐
                    │  Agent 1 Slot Manifest │
                    └──────────┬───────────┘
                               │
           ┌───────────────────┴───────────────────┐
           │                                       │
           ▼                                       ▼
┌─────────────────────┐              ┌─────────────────────┐
│  Agent 2            │              │  S3                 │
│  (bank query specs) │              │  (sim generator)    │
└──────────┬──────────┘              └──────────┬──────────┘
           │                                    │
           ▼                                    ▼
┌─────────────────────┐              ┌─────────────────────┐
│  Non-sim candidates │              │  Sim candidates     │
│  (tagged questions) │              │  (tagged, Format:Sim)│
└──────────┬──────────┘              └──────────┬──────────┘
           │                                    │
           └────────────────┬───────────────────┘
                            │
                            ▼
              ┌─────────────────────────┐
              │  STEP 1: CODE           │
              │  Group candidates by    │
              │  slot (topic + type)    │
              └──────────┬──────────────┘
                         │
                         ▼
              ┌─────────────────────────┐
              │  STEP 2: SUBAGENT 3b    │
              │  Semantic Fit &         │
              │  Distractor Alignment   │
              │  + Diagnostic Reports   │
              └──────────┬──────────────┘
                         │
                         ▼
              ┌─────────────────────────┐
              │  STEP 3: CODE           │
              │  Fallback if empty      │
              └──────────┬──────────────┘
                         │
                         ▼
              ┌─────────────────────────┐
              │  STEP 4: CODE           │
              │  Selected Items Manifest│
              └──────────┬──────────────┘
                         │
                         ▼
              ┌─────────────────────────┐
              │  To Agent 4             │
              │  (Sequencer)            │
              └─────────────────────────┘
```

---

## 7. Edge Cases

| Scenario | Handling |
|----------|----------|
| Multiple candidates for one slot, all equal | Prefer bank over sim (bank is validated); then pick by highest confidence |
| Zero candidates, fallback also empty | Flag `MISSING_BANK_ITEM`, continue to next slot. Agent 5 decides retry or proceed |
| Sim candidate exists but bank candidate is better fit | Pick bank — sim was a backup option |
| Slot with `style_constraint: "calculation"` and only Theory candidates | Fallback to nearest-matching Type |
| Same question appears in both pools (collision) | Deduplicate by question text before grouping |

---

## 8. Open Questions

- [ ] Should the subagent receive ALL slot candidates at once (batched) or one slot at a time (sequential)?
- [ ] When `MISSING_BANK_ITEM` is flagged, should Agent 5 re-run S3 to generate a replacement sim question for that slot?
- [ ] Should the selected items include the full question text or just an ID + rationale?
- [ ] How to handle sim questions in Theory format (multi-part a/b/c)?
