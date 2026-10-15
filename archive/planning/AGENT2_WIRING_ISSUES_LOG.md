# Agent 2 Wiring — Issues & Root-Cause Log

Date logged: 2026-07-31

---

## 1. Sample question banks have no tags
**Why we have it:** The question-bank tag format
(`[Type: ...; Subject: ...; Topic: ...; Format: ...]`) was introduced with the
question-generator revision, but the real bank files
(`X/physics/topicfolder1/question_bank.txt`) were never migrated to it — they
still use plain untagged text. Agent 2's tag index (`_build_bank_tag_index`),
the orchestrator's topic resolution, and the file retriever all depend on
these tags, so against current data they all return empty results.

**Impact:** Agent 2 output cannot be validated end-to-end with the existing
library. Pipeline only works once banks are tagged (or a retagging/migration
step is added).

**Decision:** RESOLVED — user will push an updated topic folder with tagged
banks (question_bank.txt + answer_bank.txt in the new tag format) to enable
accurate testing. Unblocks issues #5 (tag index), retriever, and Agent 2
end-to-end verification.

---

## 2. Agent 2 output is a dead-end until Agent 3 exists
**Why we have it:** The pipeline is being built bottom-up. Agent 1 was wired
first (with a temporary fall-through to the legacy blueprint flow), and Agent 2
is being wired next — but Agents 3–5 (which consume Agent 2's query spec and
candidate pool) don't exist yet. Type in Agent 2's world is
MCQ/Hybrid/Theory (new tag model), while the app's legacy LOAD state still uses
MCQ/SUBJ + Section A/B, so the legacy path cannot consume the new manifest.

**Impact:** The retriever is built against a schema nothing reads yet; no
end-to-end verification until Agent 3 is wired.

**Decision:** RESOLVED — Option B: wire Agent 2 + retriever fully now, keep
the temporary legacy fall-through in the quiz UI, AND add a standalone
verification harness (`dev_test_agent2.py`) that runs the Agent 2 pipeline
directly against the tagged sample bank to validate the manifest + candidate
pool before Agent 3 exists. Agent 3 will later consume the stored pool.

---

## 3. Code steps between agentic steps force calling subagents directly
**Why we have it:** The updated approach (SUBAGENT_AUDIT.md) splits Agent 2
into two AI steps (2a topic resolution, 2c fallback construction) with two code
steps in between (2b tag mapping, 2d output formatting). Faithfully implementing
that means the app must run code BETWEEN agent calls: call 2a → code 2b → call
2c → code 2d. But opencode subagents are designed to be called by their parent
orchestrator agent, not directly by the app — which conflicts with the earlier
design decision that "the app never calls subagents directly."

**Impact:** Either the orchestrator does 2b inside its prompt (making it AI
instead of code — the drift risk in issue #4), or the app calls the AI steps
directly (violating the subagent rule).

**Proposed direction (user):** Build 2a and 2c as PRIMARY agents (not
subagents) so the app can call each directly and interleave the code steps.
User builds all agents as primary agents. If adopted, the `agent2_query_specifier`
orchestrator prompt becomes unnecessary — the app drives the sequence.

**Decision:** RESOLVED — the issue is real. Fix adopted: 2a and 2c are built
as PRIMARY agents (user builds them) named `agent2a-topic-resolver` and
`agent2c-fallback-builder`; the app calls each directly and interleaves the
code steps. The `agent2_query_specifier` orchestrator prompt is DROPPED — the
app drives the sequence. Step 2b tag mapping moves to app code
(`tag_mapping.py` lookup table), making it deterministic with no model drift.

**Note:** This issue likely applies beyond Agent 2 — any future agent whose
subagent steps are separated by code steps (e.g. Agent 3's code-grouping
before subagent 3b, Agent 5's code audit before subagents 5b/5c) will face the
same choice. The primary-agent pattern adopted here should be the default for
the remaining pipeline unless a step genuinely requires a parent orchestrator.

---

## 4. Step 2b (tag mapping) runs inside the orchestrator prompt
**Why we have it:** Per SUBAGENT_AUDIT.md, Agent 2 uses the "updated approach":
only judgment steps (2a, 2c) are subagents; mechanical steps (2b tag-mapping
lookup, 2d formatting) are NOT AI subagents. So 2b lives in the orchestrator's
prompt as a fixed lookup table. The codebase already documents that small/fast
models don't reliably obey constraints, so the orchestrator may drift from the
table.

**Impact:** Possible wrong Type/Format assignments per slot; risk is silent
(wrong tags → retriever finds nothing or finds wrong-fit questions).

**Decision:** RESOLVED — dissolved by the Issue #3 decision: 2b becomes
deterministic `tag_mapping.py` app code (no model drift). Lookup table
confirmed: prerequisite_repair→MCQ, conceptual_gap→Hybrid, transfer_mechanism→
Theory (default); style=calculation→Hybrid, style=proof→Theory; Format→Non-Sim
for all; user section preferences applied as a code pre-filter.

---

## 5. `_extract_json()` returns dicts only and does no schema validation
**Why we have it:** Inherited directly from the Agent 1 wiring
(`_extract_json` was written to parse the quota manifest). It handles direct /
fenced / brace-extracted JSON, returns `None` on failure, and does not check
that required keys like `file_query_specs` / `search_tiers` exist.

**Impact:** A bare-array or structurally-wrong orchestrator response passes
silently or errors with a generic message; the retriever then finds nothing.

**Decision:** RESOLVED — systems-engineer approach approved:
1. Generalize `_extract_json()` to return `dict | list | None` (bare arrays parse).
2. New `main_app/manifest_validator.py` (stdlib only) with per-stage contracts:
   `validate_quota_manifest`, `validate_query_spec_manifest`,
   `validate_candidate_pool`. Each returns a list of specific error strings;
   empty = valid.
3. Fail fast with descriptive error (e.g. "Query spec manifest invalid: slot 4
   missing tier_2_topic_fallback") surfaced via the existing error screen.
   No auto-retry (Agent 5's domain) and no auto-repair of bad manifests.
Validators run before a manifest is stored or consumed; the pattern is reused
for Agents 3-5 later.

---

## 6. Stale manifests persist across quiz sessions
**Why we have it:** `clear_sessions()` was written before the new manifest
keys existed. It clears agent sessions + pending messages but not
`quota_manifest`, and (new) `query_spec_manifest` / `candidate_pool` stored in
`~/.quiz_app/config.json`. A quiz that fails mid-pipeline leaves stale data a
later run could read.

**Impact:** Cross-session contamination; downstream agents may read a previous
quiz's allocations.

**Decision:** RESOLVED — simple approach agreed: manifests stay keyed
generically in config (overwritten per quiz, never deleted on `clear_sessions()`);
stages pass manifests explicitly in-memory between callbacks rather than trusting
config mid-pipeline. Full session/artifact archive is a separate future feature
(see Issue #11) — it will snapshot manifests under named sessions instead of
deleting them.

---

## 7. Error message mislabel on Agent 2 failure
**Why we have it:** The temporary bridge reuses `_on_blueprint_error()`
(which says "Blueprint generation failed") for convenience, since Agent 2 was
added as a step inside the THINK state. That label is now inaccurate.

**Impact:** User sees a misleading error message if Agent 2 fails.

**Decision:** RESOLVED — two failure classes, two message shapes
(implemented in new `main_app/pipeline_errors.py` + `_on_pipeline_error()`):
1. **EXACT** — failure is deterministically identified (e.g. manifest
   validator lists the precise invalid fields, or the app's state machine knows
   which stage is running). Single precise message; no cause list.
2. **AMBIGUOUS** — the app cannot resolve the root cause (CLI/network failure,
   agent returned prose/empty, empty candidate pool whose trigger is unknown).
   Message shows the failure plus an ORDERED list of probable causes — a chain
   to check in order.

Also fixed the mislabel: `_on_blueprint_error()` renamed to
`_on_pipeline_error(token, stage, msg)` — each call site passes its real stage
(Agent 1 → 'quota planning', legacy blueprint → 'blueprint generation'). Agent 2
stages will pass theirs ('topic resolution', 'fallback construction').

---

## 8. Candidate pool in config.json may bloat the file
**Why we have it:** The existing pattern stores agent outputs
(quota manifest) in `~/.quiz_app/config.json`. The candidate pool contains
full question texts for many slots × candidates — far larger than the quota
manifest.

**Impact:** Slow config read/write; large config file.

**Decision:** RESOLVED — candidate pool kept **in-memory on QuizPage only**,
passed explicitly between callbacks, never written to config.json. The
query_spec_manifest (small) stays in config; the pool (full question texts) is
transient. Consistent with Issue #6's explicit in-memory passing.

---

## 9. Agent-name handshake between code and registration
**Why we have it:** The app references agents by string constants in
`agent_runner.py` (`query-specifier`, `agent2a-topic-resolver`,
`agent2c-fallback-builder`). The user registers agents in
`~/.config/opencode/opencode.json` — names must match exactly or calls fail.

**Impact:** Silent/direct failure if names diverge; hard to spot until runtime.

**Decision:** RESOLVED — startup check: the app verifies at launch that
`diagnostic-quota-planner`, `agent2a-topic-resolver`, and
`agent2c-fallback-builder` are registered in opencode.json, and fails with a
clear list of which are missing. Deterministic catch; the Issue #7 probable-cause
chain remains as the runtime fallback.

---

## 10. Pre-existing LSP / type-hint noise
**Why we have it:** `config.py` and `quiz_page.py` contain long-standing
`Optional`/`Unknown | None` type-hint warnings (e.g. `_blueprint`, `_quiz_log`
accessed when possibly `None`). Not introduced by this work.

**Impact:** None at runtime; cosmetic noise in the editor.

**Decision:** RESOLVED — leave as-is. Cosmetic, runtime-safe, not introduced
by this work; keeps wiring scope tight.

---

## 11. FUTURE FEATURE — Quiz artifacts & state save (Backlog)
**Why we have it (desired feature):** The user wants to store each completed
quiz as an **artifact** and later choose what to do with it:
  1. **Retake exact quiz** — same questions, same order.
  2. **Retake quiz framework, new questions** — reuse the diagnostic state
     (background reports + quota manifest + user request) but regenerate the
     quiz against updated question banks.
  3. **Add questions to the same quiz** — extend an existing artifact's count
     using its quota categories.

**Design note:** The manifests ARE the artifact layers:
- Diagnostic layer (background reports + quota manifest) → scenarios 2 & 3.
- Retrieval layer (query spec manifest) → only meaningful if banks are
  unchanged; regenerated for scenario 2.
- Payload layer (Agent 5's ordered quiz, full texts embedded) → scenario 1
  and the base for scenario 3.
- Candidate pool → transient; low value after selection.

**Impact:** Reframes Issue #6 — manifests must be snapshotted under named
sessions, never deleted. `clear_sessions()` only resets the active-session
pointer.

**Status:** BACKLOG — not part of Agent 2 wiring. Designed when the artifact
screen/feature is built.

---

## 12. Theory sub-parts have no sequential handling in the app
Date logged: 2026-08-04

**Why we have it:** The question bank stores each theory question as ONE numbered
entry whose sub-parts `(a) (b) (c) (d) ...` are continuation lines. The parser
joins them into a single `question_text`, and `build_question_list()`
(`question_generator.py:346`) assigns the entire multi-part block to non-MCQ
questions. Nothing in the app knows theory questions carry ordered sub-parts —
they are displayed all at once and evaluated as one answer blob.

**Impact:** The app cannot show theory sub-parts one after the other as the
user intends. There is also a latent trap: `split_mcq`'s option regex
(`answer_matcher.py:250`, `^([A-Da-d])[.)]\s+`) matches `(a)`, `(b)`, `(c)`
sub-part lines. It is safe today only because `split_mcq` is gated behind
`q_type == 'MCQ'`; any future call on a Theory question would mis-treat its
sub-parts as multiple-choice options.

**Proposed direction (user):** When wiring resumes, the app should present
theory sub-parts sequentially — part (a) first, then (b), etc. — each with its
own input, and evaluate per part against its matching answer-bank sub-part.

**Decision:** OPEN — design agreed, not implemented. No bank format change is
needed: the generator already line-delimits sub-parts `(a)(b)(c)(d)` in
`question_bank.txt` and will keep the same headers in `answer_bank.txt`. Wiring
plan agreed:
1. Add a Theory sub-part splitter (regex `^\(([a-z])\)\s+` on question and
   answer text) producing an ordered sub-part list.
2. Split the answer-bank entry the same way so each sub-part has its own
   reference answer. Rule: theory entries in `answer_bank.txt` MUST keep the
   `(a)(b)(c)...` headers matching their question.
3. UI shows the parts sequentially, one input each; all parts keep the parent
   question's number so bank pairing and scoring stay intact.
  4. Never route Theory through `split_mcq`; add an explicit type guard.

---

## 13. CLI bridge "opencode returned empty response" flakiness
Date logged: 2026-08-05

**Why we have it:** `CLIBridgeClient.call()` (`api_client.py`) shells out to
`opencode run --format json`. Live runs were intermittently (sometimes
deterministically) failing with "opencode returned empty response" even though
the agent session actually completed. Three distinct root causes found:

1. **PTY output.** The bridge spawned opencode on a `pty.openpty()` pair. When
   stdout is a TTY opencode switches to its interactive/TUI output path, which
   is not clean JSONL — `_extract_response_from_json` then found nothing.
   Replaced with plain pipes (stdout + stderr captured separately).
2. **Truncated event stream.** Even with pipes, `--format json` sometimes emits
   only a single `step_start` line to stdout and nothing else, while the session
   completes internally (confirmed via `--print-logs`: `message.part.*` events
   are published on the internal bus but never reach stdout). The model also
   occasionally returns an empty first response (`step=1 loop` → `exiting loop`
   with no text part), which opencode exits rc 0 and silently.
3. **Result**: `on_error("opencode returned empty response.")` surfaced as a
   dead-end "Agent 2 failed" / "candidate-selector agent call failed" block.

**Fix (implemented in `api_client.py`):**
- Run opencode on plain pipes, not a PTY.
- Retry loop: up to 5 attempts (3s backoff) on empty response or non-zero exit.
- **DB fallback**: `_read_session_text_from_db(session_id)` — when stdout has
  no text but a `sessionID` was captured, read the last `text` part for that
  session from opencode's SQLite store
  (`~/.local/share/opencode/opencode.db`, `part` table). opencode persists the
  full assistant reply there even when stdout streaming fails.

**Verification:** The full live chain now passes —
`dev_test_agent3.py "X/chem/L1.1 Definition and Scope of Chemistry"` runs
Agent 2 (2a → tag mapping → 2c) → file retriever → Agent 3
(3a grouping → 3b live candidate selector → 3d assembly → validation) to exit 0
with a valid selected-items manifest. Live 3b test:
`{total_slots: 3, successful_matches: 2, missing_count: 1}` with slot 3 (bogus
topic) correctly MISSING.

**Notes:**
- `--print-logs` output confirmed the empty-response is upstream
  (model/opencode run event emission), not Agent 3 wiring.
- The 3b agent sometimes omits per-selection `match_confidence` /
  `selection_rationale` (rationale returned as markdown prose outside the JSON).
  `_parse_3b_selections` now normalizes field aliases (`rationale`, `confidence`)
  and falls back to a neutral rationale so the manifest still validates.

---

## 14. Agent 4 (sequencer) wiring
Date logged: 2026-08-05

**Why we have it:** Agents 1–3 produce the question *content*; the final quiz
order was still the legacy blueprint fall-through. The blueprint requires a
pedagogically-sequenced quiz (warm-up → core → transfer) consumed by Agent 5.

**Decision:** RESOLVED — Agent 4 wired as a split pipeline
("judgment AI, mechanical code"):

- 4a: `agent4a-pacing-arc` (primary agent, registered in opencode.json) chooses
  the pacing arc template + stage sequence — the only AI judgment step.
- 4b–4d: `main_app/sequencer.py` deterministically buckets by objective type →
  pacing stage, sorts within stage by confidence, picks the most approachable
  item as the warm-up Gateway (position 1), keeps same-topic / same-sim-set
  items consecutive, and assembles the Agent 5 manifest.
- Validation via `validate_sequenced_quiz`; persisted via
  `save_sequenced_quiz` (small manifest only — full text stays in memory,
  Issue #8 pattern).
- `quiz_page._on_selection_ready` now calls `call_sequencer` →
  `_on_sequenced_ready` → `build_questions_from_sequence` → quiz start.
  Legacy `_legacy_generate_blueprint` kept as fallback when the agent runner
  is unavailable.

**Verification:** `dev_test_agent4.py --mock` (offline functional) and the live
chain (`X/chem/L1.1 Definition and Scope of Chemistry`) both exit 0. Live run:
Agent 2 → retriever → Agent 3 → Agent 4a (Balanced Arc) → sequenced manifest
(total_questions 2) → quiz-ready question list.

**Notes:**
- Sim sets are already kept consecutive by the sequencer's grouping key
  (`sim_name` + `sim_set` outranks topic grouping); the sim-group renderer
  path is exercised once sim-generated candidates land in the pool.
- The 4a agent may omit `target_cognitive_flow`/`stage_sequence`; the parser
  tolerates that and `sequencer.build_ordered_sequence` defaults to the
  Balanced Arc stage order.

---

## 15. Agent 5 (compliance auditor) wiring
Date logged: 2026-08-05

**Why we have it:** After Agent 4, the quiz went straight to the Quiz UI with
no final gatekeeper. The blueprint requires a compliance audit (structural
integrity, diagnostic alignment, user-preference compliance) before the payload
ships.

**Decisions (user-confirmed):**
- FAILED path: **1 automatic retry** of the AI audits, then surface the failure
  + targeted rebuild directive. Structural failures surface immediately (they
  indicate a pipeline bug, not retryable by re-auditing).
- 5b/5c run **in parallel** (independent inputs: reports vs user request).
  `CLIBridgeClient.call()` spawns its own daemon thread, so firing both calls
  back-to-back gives concurrency for free.
- Shipped payload is **sanitised but keeps pacing metadata**
  (`pacing_stage`, `objective_type`, `position_rationale`).
- `MISSING_BANK_ITEM` slots: **proceed with reduced count**, noted in the
  verdict (`missing_items_note`) — not a failure by itself.
- Agents named `agent5b-diagnostic-audit` / `agent5c-preference-audit`
  (primary, consistent with 3b/4a).

**Implementation:**
- `main_app/compliance_auditor.py`: `audit_structural` (length, unique items,
  field integrity, tag consistency, sim-set contiguity), `assemble_audit_result`
  (decision gate), `build_production_payload` / `rebuild_sequence_manifest`
  (sanitise + round-trip).
- `call_compliance_audit` in `agent_runner.py` (parallel 5b/5c, retry-once,
  `_parse_5b_verdict` / `_parse_5c_verdict` tolerant of check-name variation).
- `quiz_page._on_sequenced_ready` now runs the audit gate →
  `_on_audit_ready` → `_start_quiz_from_sequence` (payload round-trip).

**Verification:** `dev_test_agent5.py --mock` (offline) and the live chain
(`X/chem/L1.1 Definition and Scope of Chemistry`) both exit 0. Live run:
Agent 2 → retriever → Agent 3 → Agent 4 → Agent 5 (structural all PASS,
5b PASS, 5c PASS) → sanitised payload of 2 questions that round-trips into a
valid quiz. All 12 pipeline agents registered, `check_registered_agents()` → [].

**Notes:**
- 5c returned its own check names (e.g. `subject_coverage`, `question_count`)
  instead of the prompt's `topic_preference`/`count_preference`; the parser
  only requires `verdict` + a `checks` array, so naming drift is harmless.
- The retry-once path (audit FAILED → one re-run of 5b/5c) is exercised only
  when a live audit fails; it was not triggered in the verification run.

---

Date logged: 2026-08-04

**Note:** These are intended roadmap items, not defects. They may each get a
numbered issue entry once design/wiring begins.

1. **Shell redesign — tkinter → Electron.** Migrate the app shell from
   tkinter to Electron for a richer UI/rendering layer.

2. **Puter.js API integration.** Use the Puter.js API so the app can access
   API keys of frontier models (e.g. DeepSeek R v4 flash) at runtime instead of
   bundling keys.

3. **New "images-instead-of-sims" format visual.** A new question format where
   questions are backed by images instead of simulations — planned to ship much
   sooner than the rest of this list.

4. **MathType-app redesign → integrated math notepad / answer sheet.** Redesign
   the existing MathType app so it can be added to the main app as a math
   notepad. It will serve as the answer sheet for every question type EXCEPT
   MCQ. The answer sheet UI will be modeled on it: user writes their solution in
   LaTeX, presses submit, and the LaTeX is recorded as the answer. Also doubles
   as a full worksheet (clipboard-like) for writing out full solutions.

5. **Diagrammatic questions.** Add questions involving drawing or plotting
   graphs, identification, or labelling.

6. **Image upload + graph workspace.** Add a means to upload images and an
   embedded graph workspace for user working/answers.
