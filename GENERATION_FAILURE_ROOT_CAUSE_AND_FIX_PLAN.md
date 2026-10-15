# Quiz Generation Failure — Root Cause and Fix Plan

Date: 2026-10-13
Affected run: 2026-10-12, maths L1.1–L1.5, 50 questions, non-simulation
Final error shown to the user:

> The sequencer received an empty selected-items list.
> No selected questions to sequence.
> Possible causes (check in order):
> 1. Agent 3 flagged every slot as MISSING.
> 2. The selected-items manifest is empty or corrupt.

---

## 1. Summary

The failure was **not** caused by a wrong message handed to any chat/LLM agent.
It is a deterministic bug in local tag-parsing code. The bank tag recognizer
rejected the tag key `Answer-Method`, so `extract_tags()` returned `{}` for
every question. That left `Type` and `Format` empty in the retrieval index,
so **no search tier could match any question** and all 50 slots were flagged
`MISSING_BANK_ITEM`, which produced the exact sequencer error above.

## 2. Root cause

Every maths bank question ends with a tag block that includes a newer key,
`Answer-Method`:

```
1. Let $U = \{...\}$. ... [Type: MCQ; Subject: Maths; Topic: L1.5 Principles of Set Theory and Notation; Format: Non-Sim; Exam: Cambridge IGCSE 0580/22; Answer-Method: text-exclusive]
```

`main_app/answer_matcher.py:30` defines:

```python
_TAG_PATTERN = re.compile(r'\s*\[(?:Type|Subject|Topic|Format|Exam):\s*[^;\]]*(?:;\s*(?:Type|Subject|Topic|Format|Exam):\s*[^;\]]*)*\]\s*$')
```

The allowlist is `Type|Subject|Topic|Format|Exam` and the pattern is anchored
to end-of-line (`\]\s*$`). The unknown trailing key `Answer-Method` makes the
match fail entirely, so `extract_tags()` returns `{}` for **every** question.

Verified directly:

```
extract_tags WITH Answer-Method    : {}
extract_tags WITHOUT Answer-Method : {'Type': 'MCQ', 'Subject': 'Chemistry', 'Topic': 'Acids', 'Format': 'Non-Sim'}
```

All 15 maths banks (30 questions each, including all 5 selected topics) carry
`Answer-Method`, and the question banks use it 2 189 of 2 190 lines.

## 3. How it cascaded to the failure

1. `build_tag_index` (`main_app/file_retriever.py:26`) falls back to the folder
   name for `Subject`/`Topic` (so those survive) but sets `type=''` and
   `format=''` because the tags parsed empty.
2. `_matches_tier` (`main_app/file_retriever.py:50`) requires exact `type` and
   `format` equality. With blanks:
   - tier_1 / tier_2 (`type: MCQ`) fail on type
   - tier_3 (`type: ANY`, `format: Non-Sim`) fails on format (`'' != 'non-sim'`)

   Re-running the persisted `query_spec_manifest` against the real banks gives
   **0 candidates for all 50 slots, every tier**.
3. `call_candidate_selector` (`main_app/agent_runner.py:1054`): all 50 slots
   empty -> `missing = 50`, `judge = {}` -> no Agent 3b call ->
   `_assemble_and_finish({})` writes `selected_items: []` with
   `successful_matches: 0, missing_count: 50` (matches `~/.quiz_app/config.json`).
4. `call_sequencer` (`main_app/agent_runner.py:1167`) sees the empty list and
   emits the exact error above.

## 4. The one "wrong message" to a chat

`_build_bank_tag_index` (`main_app/agent_runner.py:1858`) is built from the same
broken index, so Agents 2a/2c were told:

```
Types: none tagged
Formats: none tagged
```

even though the banks are fully tagged (`MCQ/Hybrid/Theory`, `Non-Sim`). That
is misleading, but it did **not** cause the failure — the agents still emitted
correct specs (e.g. `subject: maths, topic: L1.5..., type: MCQ, format: Non-Sim`).
The kill happened in the local matcher, after the chats succeeded.

## 5. Regression point

`git show fd380dd` ("Expand library topics…", Oct 8) added the maths banks
**with** the `Answer-Method` key and did not update `main_app/answer_matcher.py`
(unchanged since the initial commit). There is no test covering
`extract_tags` / `retrieve_candidates`.

## 6. Evidence summary

| Item | Value |
|---|---|
| Exact failure | `call_sequencer` empty selected-items (`agent_runner.py:1167`) |
| Persisted state | `selected_items`: total_slots 50, successful_matches 0, missing 50 |
| Failing tier checks | tier_1 / tier_2 / tier_3 = 0 matches each (verified) |
| Trigger | `Answer-Method` tag -> `extract_tags()` returns `{}` |
| Bug site | `_TAG_PATTERN`, `main_app/answer_matcher.py:30` |
| Introduced | commit `fd380dd` (banks added with new tag, parser unchanged) |

---

# Fix Plan

Scope: fix the generation pipeline failure at its root. Add a guard so this
class of failure surfaces immediately instead of masquerading as "all slots
MISSING", and add regression tests.

Out of scope (unless requested): the multi-hour pre-quiz chat session churn and
the OpenCode model `stream error` / timeout retry storm. The two-group
answer-bank parsing quirk is touched by the fix but is a separate pre-existing
bug (see section 4 of the plan).

## Step 1 — Core fix: `main_app/answer_matcher.py`

Current single allowlist regex (`answer_matcher.py:30`) recognises only
`Type|Subject|Topic|Format|Exam` and requires a single bracket group. Real data
uses the additional trailing key `Answer-Method`, and maths answer banks use two
adjacent groups: `[Type: MCQ ] [Answer-Method: text-exclusive]`.

Replace the fixed allowlist with a small structural parser:

- New trailing-run matcher: `(?:\s*\[[^\[\]]*\])+\s*$` (one or more adjacent
  bracket groups at end of line).
- Parse each group's contents as `Key: value` pairs split on `;` and the first
  `:`; require every key to match `^[A-Za-z][A-Za-z0-9_-]*$`.
- Accept the run as tags **only if it contains at least one core key**
  (`type|subject|topic|format|exam`, case-insensitive). This prevents eating
  legitimate content brackets such as `[2 marks]` or a leading
  `[FIGURE: …]` / `[DIAGRAM: …]`.
- `strip_tags()` removes the matched run when valid, otherwise returns the text
  unchanged.
- `extract_tags()` returns all parsed pairs (including `Answer-Method`) when
  valid, otherwise `{}`.

This keeps `parse_bank_with_tags`, `parse_numbered_bank`, `find_question_match`
and `flashcard_builder` working without changes, and tolerates future keys.

**Alternative (minimal risk):** add `Answer-Method` to the allowlist. One-line
fix, but stays brittle and does not fix the two-group answer-bank case. Not
recommended as the primary fix.

## Step 2 — Defensive guard: fail loud, not silent

In `file_retriever.build_tag_index` / `agent_runner._build_bank_tag_index`
(`agent_runner.py:1858`): when the index is non-empty but **no entry carries a
`type` or `format`**, tag parsing has effectively failed against the bank format.
Return or raise a distinct signal so generation fails fast with an accurate
message (for example, "Bank tags could not be parsed; check the question-bank
tag format") instead of silently producing 0 candidates and later reporting
"empty selected-items list".

## Step 3 — Regression tests: new `tests/test_tag_parsing.py`

Follow the repo's existing lightweight style (module-level `assert` plus
`print('PASS …')`, runnable with `python tests/test_tag_parsing.py`). There is no
pytest config and no current `answer_matcher` coverage. Cases:

1. `extract_tags` parses a maths line containing `Answer-Method`.
2. `extract_tags` parses a two-group answer-bank line `[Type: MCQ ] [Answer-Method: …]`.
3. `strip_tags` returns bare content and preserves a leading `[FIGURE: …]` / `[DIAGRAM: …]`.
4. `parse_bank_with_tags` yields correct `Type` / `Format` for a maths-style line.
5. Negative: trailing `[2 marks]` / `[Figure 1]` are **not** treated as tags.
6. End-to-end: `build_tag_index` + `retrieve_candidates` with a minimal one-slot
   query spec returns candidates (the regression that would have caught this bug).

## Step 4 — Verification

- `python tests/test_tag_parsing.py`.
- Re-run the read-only retrieval probe against the persisted
  `query_spec_manifest` and selected topics; expect non-zero candidates for all
  50 slots (currently 0).
- Optional: regenerate the maths 50-question, non-simulation quiz end-to-end and
  confirm it produces 50 items.

## Related issue to decide on

Chemistry answer banks place all 30 answers on a single line, so only entry #1
parses, and tags sit in separate bracket groups. This is pre-existing and not
what failed the maths run, but it affects answer text and flashcard tags. Options:
fold the cleanup into this change, or file it separately.

## Open questions

1. Preferred approach: robust structural parser (recommended) or minimal
   allowlist extension?
2. Include the fail-fast tag-index guard (Step 2)?
3. Fold in the answer-bank two-group / single-line cleanup, or keep this change
   strictly to the question-bank retrieval failure?
4. Any objection to adding `tests/test_tag_parsing.py` in the existing
   assert-script style?
