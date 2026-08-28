# Question Bank Population Log

**Date:** 2026-08-04
**Status:** Question bank population PHASE COMPLETE — moving to a new direction.

---

## Summary

Populated question banks (`question_bank.txt`) and answer banks (`answer_bank.txt`) into topic folders under `X/<subject>/<topic>/`.

### Banks present (23 question banks, 18 answer banks)

| Subject | Topics |
|---------|--------|
| bio | Topic 1–5 (all 5, both files) |
| chem | L1.1–L1.5 (all 5, both files) |
| economics | L1.1, L1.2 (both files) |
| maths | L1.1–L1.5 (both files) |
| physics | L1.1–L1.5 (question banks only), topicfolder1 (both files) |

### Work completed this session
- bio Topic 4 (skipped earlier) — question + answer banks added
- bio Topic 5 — answer bank added (question bank existed)
- chem L1.1–L1.5 — new subject, question + answer banks
- economics L1.1, L1.2 — new subject, question + answer banks

---

## Open Issues

### 1. Economics L1.2, Q29 table — missing "Expected Lifetime Social Return" values
- **File:** `X/economics/L1.2 The Problem of Scarcity and the Concept of Choice/question_bank.txt` (lines ~108–112)
- **Issue:** The 4th column header ("Expected Lifetime Social Return (Millions)") exists, but the per-row social-return figures for projects 1, 3, and 4 were lost during copy-paste. Only Project 2 = **$260M** is recoverable (from answer key 29b).
- **Impact:** Question 29(b) ("calculate the explicit opportunity cost ... in terms of foregone social returns") is answerable using the known $260M figure, but the table is incomplete.
- **Fix needed:** Provide the four social-return values as a plain list (e.g., `1=..., 2=260, 3=..., 4=...`) to avoid table-format loss.

### 2. Pre-existing gap — physics answer banks missing
- The five `X/physics/L1.1`–`L1.5` folders contain `question_bank.txt` but **no `answer_bank.txt`**.
- `X/physics/topicfolder1/` is the only physics folder with both files.
- This gap predates the current session and was not closed.

---

## Next Direction

Populating question/answer banks is complete for the current scope. New development direction TBD by the user.
