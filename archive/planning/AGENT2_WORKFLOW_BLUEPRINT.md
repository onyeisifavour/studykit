# Agent 2: Metadata Query Specifier — Redesigned Workflow Blueprint
## 1. Purpose
Agent 2 translates abstract quota allocations from Agent 1 into precise
file-system search parameters using only the 4 available question bank tags:
**Subject**, **Topic**, **Type**, **Format**.
It solves the **"Where is this math stored?"** problem — mapping abstract
diagnostic needs (like "prerequisite flaw on Quadratics") to the actual topic
file that contains the prerequisite math (e.g. "Factoring Polynomials").
---
## 2. Architecture
```
         AGENT 1 QUOTA MANIFEST
                    │
                    ▼
┌─────────────────────────────────────┐
│  Step 1: Topic Taxonomy &           │
│  Prerequisite Resolution            │ ← Subagent 2a
│  (resolve generic topic → actual    │
│   file topic using concept block)   │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  Step 2: Structural Tag Mapping     │ ← Code
│  (flaw category → Type: MCQ/Hybrid/ │
│   Theory; Format → Non-Sim)         │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  Step 3: Multi-Tier Fallback        │ ← Subagent 2c
│  Search Construction                │
│  (3 tiers: exact → topic fallback → │
│   type relaxation)                  │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  Step 4: File Query Spec Output     │ ← Code
│  (format as JSON manifest)          │
└──────────────┬──────────────────────┘
               │
               ▼
         FILE QUERY SPEC MANIFEST
               │
               ▼
         AGENT 3 (Candidate Evaluator)
```
---
## 3. Inputs
### 3.1 Agent 1 Quota Manifest
```json
{
  "quiz_metadata": {
    "total_questions": 10,
    "primary_objective": "Prerequisite repair and conceptual transfer"
  },
  "slot_allocations": [
    {
      "slot_number": 1,
      "objective_type": "prerequisite_repair",
      "topic": "Distributive Property",
      "target_issue": "Partial Distribution Error",
      "style_constraint": "calculation"
    },
    {
      "slot_number": 2,
      "objective_type": "conceptual_gap",
      "topic": "Quadratic Equations",
      "target_issue": "Discriminant Interpretation",
      "style_constraint": "none"
    }
  ],
  "modifiers": {
    "focus_topic": "Quadratic Equations",
    "style_constraint": "calculation"
  }
}
```
### 3.2 Concept Block Taxonomy
The canonical reference mapping topic names to prerequisites:
```
Quadratic Equations → Prerequisites: Factoring Polynomials, Distributive Property
Distributive Property → Prerequisites: Basic Arithmetic
...
```
### 3.3 Question Bank File Index
Valid tag values that exist in the question bank:
```
Subject: Mathematics, Physics, Chemistry
Topic: Linear Equations, Distributive Property, Factoring Polynomials,
       Quadratic Equations, SI Units, Scientific Notation, ...
Type: MCQ, Hybrid, Theory
Format: Non-Sim
```
---
## 4. Step-by-Step Process
### Step 1: Topic Taxonomy & Prerequisite Resolution (Subagent 2a)
**Input:** Slot allocation + Concept Block taxonomy
**Process:**
- For `conceptual_gap`, `transfer_mechanism`, `synthesis_elevation`:
  Use the topic directly from the slot.
- For `prerequisite_repair`:
  Consult the concept block to find the prerequisite topic that contains
  the specific `target_issue`. E.g. a prerequisite_flaw on "Quadratic
  Equations" with target_issue "Factoring Error" resolves to the file
  topic "Factoring Polynomials" — not "Quadratic Equations".
**Output:**
```json
[
  {
    "slot_number": 1,
    "slot_objective": "prerequisite_repair",
    "resolved_topic": "Distributive Property",
    "resolved_subject": "Mathematics",
    "target_issue": "Partial Distribution Error",
    "keywords": ["partial distribution", "distribute", "negative signs"]
  },
  {
    "slot_number": 2,
    "slot_objective": "conceptual_gap",
    "resolved_topic": "Quadratic Equations",
    "resolved_subject": "Mathematics",
    "target_issue": "Discriminant Interpretation",
    "keywords": ["discriminant", "b^2-4ac", "roots", "nature"]
  }
]
```
---
### Step 2: Structural Tag Mapping (Code)
**Input:** Resolved slot list from Step 1 + Agent 1 modifiers
**Process** — deterministic lookup table:
| Slot Objective | Default Type | Style=calculation | Style=proof |
|---------------|-------------|-------------------|-------------|
| prerequisite_repair | MCQ | Hybrid | Theory |
| conceptual_gap | Hybrid | Hybrid | Theory |
| transfer_mechanism | Theory | Hybrid | Theory |
| synthesis_elevation | Theory | Theory | Theory |
Also applies user preference filters (e.g. if `section_a_sim` is disabled,
only use non-sim formats).
**Output:** Enriched slot list with Type and Format assigned
---
### Step 3: Multi-Tier Fallback Construction (Subagent 2c)
**Input:** Enriched slot list from Step 2
**Process:** For each slot, construct 3 search tiers:
| Tier | What it does | When it's used |
|------|-------------|----------------|
| Tier 1 (Exact) | Resolved topic + assigned Type | Primary search |
| Tier 2 (Topic Fallback) | Parent/broader topic + same Type | If Tier 1 yields 0 results |
| Tier 3 (Type Relaxation) | Broader topic + ANY Type | If Tier 2 yields 0 results |
**Output:**
```json
{
  "file_query_specs": [
    {
      "slot_number": 1,
      "slot_objective": "prerequisite_repair",
      "search_tiers": {
        "tier_1_exact": {
          "subject": "Mathematics",
          "topic": "Distributive Property",
          "type": "MCQ",
          "format": "Non-Sim",
          "search_keywords": ["partial distribution", "negative signs"]
        },
        "tier_2_topic_fallback": {
          "subject": "Mathematics",
          "topic": "Linear Equations",
          "type": "MCQ",
          "format": "Non-Sim",
          "search_keywords": ["distribution"]
        },
        "tier_3_type_relaxation": {
          "subject": "Mathematics",
          "topic": "Linear Equations",
          "type": "ANY",
          "format": "Non-Sim",
          "search_keywords": []
        }
      }
    }
  ]
}
```
---
### Step 4: File Query Spec Output (Code)
Formats the final JSON manifest. Also generates file paths for the file
retriever to load:
```python
def build_file_queries(query_specs, base_path):
    """Generate file paths that the file retriever will open."""
    queries = []
    for spec in query_specs:
        for tier_key, tier in spec["search_tiers"].items():
            file_path = f"{base_path}/{tier['subject']}/{tier['topic']}/{tier['type']}_{tier['format']}.txt"
            queries.append({
                "slot_number": spec["slot_number"],
                "tier": tier_key,
                "file_path": file_path,
                "keywords": tier.get("search_keywords", []),
            })
    return queries
```
---
## 5. Data Flow to Downstream
```
Agent 2 Output (File Query Spec Manifest)
                    │
                    ▼
         FILE RETRIEVER (code)
         │
         ├── For each slot, try Tier 1 file
         ├── If file missing → try Tier 2
         ├── If still missing → try Tier 3
         └── Load all candidate questions into memory
                    │
                    ▼
         CANDIDATE QUESTION POOL
         (raw text grouped by slot)
                    │
                    ▼
         AGENT 3 (Candidate Evaluator)
```
---
## 6. Subagent Summary
| Component | Type | File | Step |
|-----------|------|------|------|
| Orchestrator | Agent prompt | `agent2_query_specifier.md` | — |
| 2a: Topic Resolution | Subagent | `agent2a_topic_resolver.md` | Step 1 |
| 2b: Tag Mapping | Code | (in orchestrator logic) | Step 2 |
| 2c: Fallback Construction | Subagent | `agent2c_fallback_builder.md` | Step 3 |
| 2d: Output Formatting | Code | (in app) | Step 4 |
---
## 7. Open Questions
- [ ] Topic/broader-topic mapping: how does 2c know the "parent topic"?
      Needs topic hierarchy in concept block.
- [ ] File naming convention: `{Type}_{Format}.txt` or just `{Type}.txt`?
      E.g. `Hybrid_Non-Sim.txt` vs `Hybrid.txt`.
- [ ] What happens when ALL 3 tiers yield empty files for a slot?
      (Fallback fallback — generate on-the-fly?)
