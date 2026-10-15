# TODO — File-backed CLI pipeline (Option A)

Chosen: **Option A** — one attachment per call = the original full prompt.
Payload ceiling: **300 KB**. Run retention: **20** (my choice).
Status: **done** (working tree, not committed).

## Fixes

- [x] **Fix 1 (Option A)** — all 9 generation calls now attach exactly one
      prompt file: quota, 2a, 2c, sim, options, 3b, 4a, 5b, 5c. The doubled
      structured + `*_instructions.md` payloads are gone.
- [x] **Fix 2** — `04_candidates.json` (the 255 KB indent-2 duplicate) is no
      longer written; 3b uses the compact `_build_candidates_text` instead.
- [x] **Fix 3** — stage-prefixed prompt files (`01_quota_prompt.md`,
      `02a_prompt.md`, `03b_prompt.md`, …); no shared or overwritten names.
- [x] **Fix 4** — run retention in `run_workspace.prune_runs` (last 20, ordered
      by mtime, never removes the run in progress). Override with
      `QUIZ_APP_RUN_RETENTION`.
- [x] **Fix 5** — payload-size guard in `CLIBridgeClient.call`: warns on stderr
      when a call's attachments exceed the ceiling. Default 300 KB, override
      with `QUIZ_APP_PAYLOAD_LIMIT_BYTES`.
- [x] **Fresh sessions per generation** — `AgentRunner.start_generation()`
      clears the 9 generation agents (memory + config) at the start of every
      `QuizService.generate_quiz`. The 5 pre-quiz chat agents are preserved;
      their diagnostic reports are read immediately before the reset.

## Agents following the new style

- [x] Confirmed live: an agent invoked with `--file <prompt.md>` plus the
      generic instruction read the attached file and returned exactly the
      requested JSON. No `~/.opencode/agent/*.md` changes are needed — the
      agent's whole task now arrives in the file instead of the inline message,
      exactly as before.

## Tests

- [x] `tests/test_file_backed_pipeline.py` — single attachment per call (AST
      guard), payload limit default/env override, attachment totals, retention.
- [x] `tests/test_generation_sessions.py` — generation sessions reset,
      pre-quiz sessions preserved.
- [x] Full suite: all 15 `tests/test_*.py` files pass.

## Notes

- Measured: the 3b attachment is ~199 KB (< 300 KB ceiling); the previous
  duplicated 3b payload was ~491 KB. 2a dropped from ~210 KB to ~105 KB.
- Live run showed the model first tries a relative `Read prompt.md` (opencode
  exposes the attached filename); it fails harmlessly because the content is
  also inlined in the `<file>` block, and the agent recovers immediately.
