# Agent 5: Compliance Auditor — Blueprint

## 1. Overview

Agent 5 is the **final gatekeeper** between the multi-agent generation pipeline
and the student-facing quiz app. It inspects the completed sequence from Agent 4
against a strict set of business logic rules, database integrity requirements,
and user preferences.

Agent 5 does **not** create, reorder, or edit question content. It simply
evaluates the entire generated quiz package and either **approves it for
deployment** or issues a **targeted rebuild directive** to a specific faulty
upstream agent.

---

## 2. Inputs

| Input | Source | Format |
|-------|--------|--------|
| Sequenced Quiz Manifest | Agent 4 | JSON — ordered questions with sequence_index, question_id, pacing_stage, position_rationale |
| Diagnostic Reports | Background models (from chat) | Free-form research reports (knowledge-graph, misconception, mechanism, drill) |
| User's Final Chat Message | Chat | Raw request, e.g. "10 questions, focus on calculations" |
| Question Bank Content | Bank files | Full texts of selected questions (for integrity checks) |

---

## 3. Step-by-Step Process

```
[Sequenced Quiz + Diagnostic Reports + User Request + Bank]
                          │
                          ▼
       1. Structural & Integrity Audit (CODE)
                          │
                          ▼
       2. Diagnostic Alignment Audit (SUBAGENT 5b)
                          │
                          ▼
       3. User Preference Compliance Check (SUBAGENT 5c)
                          │
                          ▼
       4. Decision Gate & Routing (CODE)
                          │
                    PASSED │ FAILED
        ┌──────────────────┴──────────────────┐
        ▼                                     ▼
  Production Quiz Payload          Targeted Retry Directive
  (sanitized, to Quiz UI)         (to faulty upstream agent)
```

---

## 4. Step Details

### Step 1: Structural & Integrity Audit (Code)

**Task:** Run deterministic verification checks on the quiz package structure.

**Checks:**
| Check | Logic |
|-------|-------|
| Unique Item Check | No `question_id` appears more than once (prevents duplicates) |
| Length Check | `len(selected_questions)` strictly matches `total_questions` (e.g. exactly 10) |
| Field Integrity | Every selected question has a complete body, correct options, and a valid answer key in the bank |
| Tag Consistency | Every question carries the 4 tags: `Type`, `Subject`, `Topic`, `Format`; sim questions keep `sim_name`/`sim_instruction` |
| Sim Set Integrity | Sim questions from the same `sim_set` remain consecutive (no split) |

**Failure behavior:** If any check fails, **skip all subagents** — go straight to
Decision Gate with `FAILED` status.

---

### Step 2: Diagnostic Alignment Audit (Subagent 5b)

**Task:** Verify that critical learning deficits identified during the chat were
not accidentally skipped.

**Input:** Sequenced quiz manifest + 4 diagnostic reports.

**Checks:**
| Check | Logic |
|-------|-------|
| Prerequisite Safety Net | If misconception-classifier flagged a HIGH-SEVERITY `prerequisite_flaw` on a topic, at least one question targeting that prerequisite must exist in the quiz |
| Over-Probing Check | If mechanism-evaluator flagged memorized understanding, the quiz must NOT consist entirely of standard recall questions — require application/mechanism questions |
| Knowledge Gap Coverage | High-priority gaps from knowledge-graph-builder must have at least one addressing question |

**Output:** JSON verdict per check (PASS/FAIL) with evidence and the specific
missing topic/question_id.

---

### Step 3: User Preference Compliance Check (Subagent 5c)

**Task:** Cross-check the final payload against the user's explicit request in
their final chat message.

**Input:** Sequenced quiz manifest + user request.

**Checks:**
| Check | Logic |
|-------|-------|
| Topic Preference | If the user named specific topics, requested topics must occupy the majority share of slots |
| Style Preference | If the user requested a style (e.g. "more calculations"), at least ~50% of questions must match — unless diagnostic evidence justifies otherwise |
| Count Preference | If the user specified a count, the manifest total must match |

**Interpretation rules:**
- Only enforce **explicit** requests; vague phrasing → lenient, note interpretation but PASS
- If user request conflicts with a diagnostic MUST-FIX flaw, prefer the diagnostic need and record the conflict

**Output:** JSON verdict per check (PASS/FAIL/NA) with `interpreted_request`.

---

### Step 4: Decision Gate & Routing (Code)

**Case A — PASSED:** All three steps passed. Strip internal agent rationales,
format into a clean sanitized runtime object, ship directly to the Quiz UI.

**Case B — FAILED:** Output a targeted error log pinpointing the exact failure
and trigger a **single-agent retry call** (e.g. tell Agent 3 to re-pick Slot 4
because of a duplicate ID). Never a full-pipeline regeneration.

**Output:**
```json
{
  "audit_status": "PASSED",
  "production_quiz_payload": {
    "total_questions": 10,
    "questions": [
      {
        "position": 1,
        "question_id": "q_alg_1010",
        "question_text": "2(x - 3) = 14. Solve for x.",
        "type": "MCQ",
        "subject": "Mathematics",
        "topic": "Linear Equations",
        "format": "Non-Sim",
        "options": ["x = 10", "x = 4", "x = 7", "x = 13"],
        "correct_answer": "x = 10"
      }
    ]
  }
}
```

```json
{
  "audit_status": "FAILED",
  "failure_reason": "DUPLICATE_QUESTION_DETECTED",
  "error_details": {
    "slot_conflict": [3, 7],
    "conflicting_id": "q_alg_1042"
  },
  "retry_instruction": {
    "target_agent": "Agent_3_Candidate_Selector",
    "action": "Re-evaluate Slot 7 candidates excluding q_alg_1042"
  }
}
```

---

## 5. Subagent Assignment

| Step | Name | AI Needed? | Verdict |
|------|------|-----------|---------|
| 1 | Structural & Integrity Audit | ❌ Deterministic checks: duplicates, count, field integrity | **Code** |
| 2 | Diagnostic Alignment Audit | ✅ Read reports + quiz, judge whether critical flaws are covered | **Subagent 5b** |
| 3 | User Preference Compliance Check | ✅ Interpret free-text user request, fuzzy match against quiz | **Subagent 5c** |
| 4 | Decision Gate & Routing | ❌ If-else: PASSED → sanitize + ship; FAILED → retry directive | **Code** |

**Total: 2 subagents** (5b, 5c) — kept separate; 5b reads diagnostic reports,
5c reads the user request, so they never share context.

---

## 6. Data Flow Diagram

```
                  ┌──────────────────────┐
                  │ Agent 4 Sequenced    │
                  │ Quiz Manifest        │
                  └──────────┬───────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
              ▼              ▼              ▼
   ┌─────────────────┐ ┌────────────┐ ┌────────────┐
   │ Diagnostic      │ │ User       │ │ Bank       │
   │ Reports (4 bg)  │ │ Request    │ │ Content    │
   └────────┬────────┘ └─────┬──────┘ └─────┬──────┘
            │                │              │
            ▼                │              │
  ┌────────────────────┐    │              │
  │ STEP 1: CODE       │◄───┴──────────────┘
  │ Structural Audit   │   (bank content for
  └─────────┬──────────┘    field integrity)
            │
            ▼ (if PASS)
  ┌────────────────────┐
  │ STEP 2: SUBAGENT 5b │◄── Diagnostic Reports
  │ Diagnostic Alignment│
  └─────────┬──────────┘
            │
            ▼ (if PASS)
  ┌────────────────────┐
  │ STEP 3: SUBAGENT 5c │◄── User Request
  │ Preference Check    │
  └─────────┬──────────┘
            │
            ▼
  ┌────────────────────┐
  │ STEP 4: CODE       │
  │ Decision Gate       │
  └─────┬────────┬─────┘
        │        │
        ▼        ▼
   PASSED      FAILED
   (sanitized  (targeted retry
   payload →   directive → Agent 2/3/4)
   Quiz UI)
```

---

## 7. Edge Cases

| Scenario | Handling |
|----------|----------|
| Duplicate question in final sequence | FAILED immediately at Step 1 — retry directive to Agent 3 |
| Question count mismatch with user request | FAILED at Step 3 (count check) unless user gave no count |
| User asked for calculations but diagnostics say calculation-style is where student fails | 5c prefers diagnostic need, records conflict, PASS with note |
| Critical prerequisite flaw uncovered | FAILED at Step 2 — retry directive to Agent 3 to add a prerequisite_repair slot |
| Sim set split across unrelated questions | FAILED at Step 1 (sim set integrity) |
| Retry loop exceeds max attempts | Escalate: relax to nearest acceptable fallback tier, then ship |
| Missing bank item from Agent 3 (`MISSING_BANK_ITEM`) | 5b decides: flag to S3 to generate a replacement sim, or proceed with reduced count |

---

## 8. Open Questions

- [ ] Max retry attempts per quiz before escalating to "proceed with reduced count"?
- [ ] Should 5b and 5c run in parallel (independent inputs) or sequentially (5b first)?
- [ ] When `MISSING_BANK_ITEM` is flagged, should Agent 5 re-run S3 to generate a replacement sim question?
- [ ] Should the production payload keep `pacing_stage` labels, or strip all internal metadata except question text/options/answers?
- [ ] Does a FAILED audit need to reach the user, or is the retry fully transparent?
