# Subagent Necessity Audit
Each step in every agent evaluated for whether it genuinely needs AI judgment
or can be handled by code.
**Key:**
- ✅ Subagent — needs judgment (reading, interpreting, reasoning)
- Code — mechanical (arithmetic, sorting, lookups, JSON templates)
---
## Agent 1: Diagnostic Quota Planner
| Step | Task | Verdict | Reason |
|------|------|---------|--------|
| 1a | Priority Hierarchy Evaluation | ✅ Subagent | Scan 4 reports, rank flaws by severity — needs nuance |
| 1b | Mathematical Quota Calculation | Code | Simple arithmetic: 30-40% of total per category |
| 1c | User Preference Adjustment | ✅ Subagent | Interpret free-text user request (topic/style modifiers) |
| 1d | Manifest Output Generation | Code | JSON template |
**Subagents: 2** (1a, 1c)
---
## Agent 2: Metadata Query Specifier (Redesigned)
| Step | Task | Verdict | Reason |
|------|------|---------|--------|
| 2a | Topic Taxonomy & Prerequisite Resolution | ✅ Subagent | Consult concept block dep. map, resolve generic topic to actual file topic |
| 2b | Structural Tag Mapping (Type & Format) | Code | Lookup table: prerequisite_repair→MCQ, conceptual_gap→Hybrid, etc. |
| 2c | Multi-Tier Fallback Search Construction | ✅ Subagent | Decide fallback priority order — needs topic relationship judgment |
| 2d | File Query Specification Output | Code | JSON template |
**Subagents: 2** (2a, 2c)
---
## Agent 3: Candidate Evaluator & Selector
| Step | Task | Verdict | Reason |
|------|------|---------|--------|
| 3a | Candidate Pool Matching | Code | Group candidates by slot_number |
| 3b | Semantic Fit & Distractor Alignment | ✅ Subagent | Read question text, compare against diagnostic reports to pick best match |
| 3c | Fallback Triggering | Code | If-else: pool empty → try next fallback tier |
| 3d | Selected Items Manifest Generation | Code | JSON template |
**Subagents: 1** (3b)
---
## Agent 4: Pedagogical Sequence Builder
| Step | Task | Verdict | Reason |
|------|------|---------|--------|
| 4a | Cognitive Arc & Pacing Curve Mapping | ✅ Subagent | Read diagnostic profile, choose "Repair First" vs "Ramp Up" arc |
| 4b | Slot Sorting & Sequencing Rules | Code | Deterministic rules: pos 1 = easiest, pos 2-4 = prerequisite repair, etc. |
| 4c | Context-Switching Optimization | Code | Group-by-topic then sort within groups |
| 4d | Final Sequenced Quiz Manifest | Code | JSON template |
**Subagents: 1** (4a)
---
## Agent 5: Compliance Auditor
| Step | Task | Verdict | Reason |
|------|------|---------|--------|
| 5a | Structural & Integrity Audit | Code | Check duplicates, count matches total, valid IDs — unambiguous |
| 5b | Diagnostic Alignment Audit | ✅ Subagent | Verify critical flaws from reports are covered in the quiz |
| 5c | User Preference Compliance Check | ✅ Subagent | Check user's explicit format/topic request was honored (fuzzy matching) |
| 5d | Decision Gate & Routing | Code | If-else: PASSED → strip rationales, deliver; FAILED → retry directive |
**Subagents: 2** (5b, 5c)
---
## Sim S1: Sim Analyzer (× N READMEs)
| Step | Task | Verdict | Reason |
|------|------|---------|--------|
| S1 | README + 4 bg reports → fit scores per flaw | ✅ Subagent | Full reasoning: evaluate sim's utility for each flaw type |
**Subagents: 1** (S1)
---
## Sim S2: Sim Placement Model
| Step | Task | Verdict | Reason |
|------|------|---------|--------|
| S2a | Score, rank, allocate sims to flaw slots | ✅ Subagent | Complex multi-factor judgment (fit score × priority × tight quota) |
| S2b | Apply user section preferences | Code | Filter by checkbox state (MCQ/Hybrid/Theory with sim) |
**Subagents: 1** (S2a)
---
## Sim S3: Sim Question Generator
| Step | Task | Verdict | Reason |
|------|------|---------|--------|
| S3 | Generate questions from placement + READMEs | ✅ Subagent | Full generation task |
**Subagents: 1** (S3)
---
## Summary
| Agent | Total Steps | Subagents | Code |
|-------|-------------|-----------|------|
| 1. Quota Planner | 4 | **2** | 2 |
| 2. Query Specifier | 4 | **2** | 2 |
| 3. Candidate Evaluator | 4 | **1** | 3 |
| 4. Sequence Builder | 4 | **1** | 3 |
| 5. Compliance Auditor | 4 | **2** | 2 |
| S1. Sim Analyzer | 1 | **1** | 0 |
| S2. Sim Placement | 2 | **1** | 1 |
| S3. Sim Generator | 1 | **1** | 0 |
| **Total** | **24** | **11** | **13** |
**11 subagent prompts** (down from 23 in the original brainstorm design).
