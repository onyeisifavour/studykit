# Moving the quiz pipeline from inline prompts to file-backed handoffs

## The problem in one paragraph

Every agent in the quiz pipeline is invoked by the Python app as
`opencode run --format json --agent <name> -s <session> <message>`, where `<message>` is the **entire** input, passed as a single `argv` element (`main_app/api_client.py`, `CLIBridgeClient.call`, the line `cmd.append(user)`). Linux caps a single argument at `MAX_ARG_STRLEN = 131072` bytes (32 × page size) and that cap cannot be raised with `ulimit`. The 3b candidate-selector prompt is **199,186 bytes**, so the `execve` fails with `[Errno 7] Argument list too long` before opencode ever runs. The same design is about to bite 2a, which is **104,918 bytes** — roughly 80 % of the limit, and it grows with the number of selected topics. This is not a model, network, or agent-registration problem; it is the kernel refusing the command line. The generic "Possible causes" list the app appends to that error is a red herring.

## Why "shorten the prompt" is the wrong fix

Trimming fields (dropping `answer_text`, capping candidates per slot) buys one more release and then fails again the moment the question bank or topic count grows. The real defect is that the app treats **conversation text as the transport for bulk data**. Any payload that scales with the library will eventually exceed `argv`, no matter how many fields you shave. The correct fix is to move bulk data out of `argv` and onto the filesystem, where it already mostly lives.

## The recommendation

**Adopt a per-run workspace and deliver bulk inputs to agents as file attachments using `opencode run --file` (Option A). Keep agents' outputs as small inline JSON that the app persists into the same workspace (Option B for outputs is explicitly rejected).**

Three reasons:

1. **It removes the failure class entirely.** `--file` puts a path on the command line and the content goes to the model through opencode's own file handling, never through `execve`. No prompt can ever be too long again.
2. **No information loss and no behavioural change.** The agent still receives the same content; the app still validates the same returned JSON. You are changing the *transport*, not the *semantics*. That keeps the blast radius small and the diff reviewable.
3. **You get an inspectable artifact trail for free.** Today the intermediate data (diagnostic reports, candidate pool, tag index) exists only in RAM and is impossible to inspect after a failure. Writing each stage's input to `~/.quiz_app/runs/<run_id>/` means any future failure can be reproduced offline by replaying a single file into a single agent.

The alternative — pass a path in the message and let the agent read it with its read tool (I'll call it Option B) — is more elegant and makes the message genuinely tiny, but it makes correctness depend on the agent choosing to call its read tool, on that tool being permitted in headless `opencode run` (no `--auto` is passed today, and the agents are declared with only `description` + `mode`, so permissions are whatever the default is), and on the cwd of the `Popen` call, which is currently unset and therefore inherits the sidecar's working directory. Do not start there. Ship Option A, and treat B as a later optimisation once A's artifacts prove stable.

## What is already on disk, and what has to be written

This is the key insight that makes the migration cheap: most of the bulk is already a file. The app reads those files into memory and then re-inlines them.

| Blob | Size (live maths selection) | Already a file? |
|---|---:|---|
| candidate pool for 3b | 162,650 B | No — derived by `file_retriever.retrieve_candidates` |
| concept blocks for 2a | 85,725 B | **Yes** — `X/<subject>/<topic>/concept_block.json` |
| diagnostic reports | 18,766 B | No — in-memory `_bg_reports`, reused by quota, 3b, 4a, 5b, options |
| slot JSON | ~19 KB | No — derived from `quota_manifest` (already persisted in config) |
| question / answer banks | 55,234 / 12,760 B | **Yes** — `question_bank.txt`, `answer_bank.txt` |
| sim READMEs | varies | **Yes** — `.../simulations/<name>/README.md` |

So the plan is: **reference library files in place; write only the derived blobs** (reports, candidates, and the small per-slot files) into the run workspace.

Two implementation facts to note now:

- `library_scanner.load_topic_files()` currently keeps only content and **drops** `question_bank_path`, `answer_bank_path`, and `concept_block_path` (only `sim_readmes` retains `folder_path`). To pass library paths you must either retain those fields or re-derive them from the selected topic folders (which `config.get_selected_topics()` already stores).
- `CLIBridgeClient.call`'s `subprocess.Popen` sets no `cwd`, so all paths you pass must be **absolute**.

## The workspace contract

Create one directory per generation run:

```
~/.quiz_app/runs/<run_id>/
  run.json                    app    metadata: run_id, created, topics, question_count
  00_request.md               app    user request + prefs + total_questions
  01_reports.json             app    the 4 background reports (deduplicates 4 separate inlines)
  02_quota_manifest.json      app    quota planner output
  03_query_spec.json          app    2c output
  04_candidates.json          app    retrieval output (the 162 KB blob)
  05_selections.json          app    3b output
  06_sequence.json            app    4a output
  07_audit_5b.json / 5c.json  app    audit outputs
  08_sim/<slot>.json          app    per-slot sim questions
  09_options/<slot>.json      app    per-slot options
```

Library files (question/answer banks, concept blocks, sim READMEs) are **referenced in place** by their absolute paths, not copied.

## The full input → output trace (for reference)

Sizes measured against the live config (5 maths topics, 60 slots, non-sim).

### Pre-quiz (chat, no files)

| Stage | Agent | Message built by | Input | Output | Persisted |
|---|---|---|---|---|---|
| main chat | `pre-quiz_main_chat` | `_format_first_message` | topic digest + student msg | tutor reply | `session_v2` + `agent_sessions` |
| 4 background | `knowledge-graph-builder` etc. (+`probe-synthesizer`/`topic-digest`) | `_send_to_background_model` | teacher/student turns | report text | **in memory only** (`_bg_reports`) |

### Generation chain

| Stage | Agent | Message built by | Input | Output | Persisted |
|---|---|---|---|---|---|
| 1 | `diagnostic-quota-planner` | `_format_quota_input` | 4 reports (18.8 KB) + request + prefs | quota manifest | `config.save_quota_manifest` |
| 2a | `agent2a-topic-resolver` | `_format_2a_input` | slots (~19 KB) + concept blocks (85.7 KB) + tag index (0.3 KB) → **104,918 B** | resolved slots | in-memory |
| 2c | `agent2c-fallback-builder` | `_format_2c_input` | enriched slots + tag index | query spec | `config.save_query_spec_manifest` |
| 3a | *(code)* | `file_retriever.retrieve_candidates` | query spec + banks | candidate pool (162,650 B, 381 cands) | in-memory |
| 3b | `agent3b-candidate-selector` | `_format_3b_input` | slots + reports + candidates → **199,186 B** | selections | `config.save_selected_items` |
| sim | `sim-question-generator` | `sim_generator.build_sim_prompt` | slot + README + math spec | question | in-memory |
| opt | `sim-option-generator` | `option_generator.build_option_prompt` | stem/answer/instruction + reports | options | in-memory |
| 4a | `agent4a-pacing-arc` | `_format_4a_input` | profile + reports | arc | `config.save_sequenced_quiz` |
| 5b | `agent5b-diagnostic-audit` | `_format_5b_input` | quiz summary + reports | verdict | `config.save_compliance_audit` |
| 5c | `agent5c-preference-audit` | `_format_5c_input` | quiz summary + request block | verdict | `config.save_compliance_audit` |

Note: the 5 maths topics have **zero simulation READMEs**, so the sim track is skipped entirely today — the current failure is purely bank-side in 3b.

### Who writes the messages the agents receive

The messages are built at runtime by the app's own Python (deterministic f-strings / `json.dumps`), not by any LLM:

| Builder | Location |
|---|---|
| `_format_quota_input` | `main_app/agent_runner.py:423` |
| `_format_2a_input` / `_build_concept_blocks_text` / `_build_bank_tag_index` | `agent_runner.py:720 / 1927 / 1896` |
| `_format_2c_input` | `agent_runner.py:741` |
| `build_sim_prompt` | `main_app/sim_generator.py:416` |
| `build_option_prompt` | `main_app/option_generator.py:275` |
| `_format_3b_input` + `_build_candidates_text` + `_build_diagnostic_reports_text` | `main_app/agent_runner.py:1679 / 1711 / 1732` |
| `_format_4a_input` | `main_app/agent_runner.py:1275` |
| `_format_5x_summary` + `_format_5b_input` / `_format_5c_input` | `main_app/agent_runner.py:1589 / 1615 / 1629` |

Separately, the **static system prompts** are hand-written markdown files in `~/.opencode/agent/`, outside the repo and not version-controlled. Six pipeline agents (3b, 4a, 5b, 5c, sim-question-generator, sim-option-generator) have **no** markdown, so for those the app-built message is the entire instruction.

## The two delivery mechanisms

| | **A. `--file` attach** | **B. path-in-message + read tool** |
|---|---|---|
| Command | `opencode run --agent 3b --file 04_candidates.json "…"` | `opencode run --agent 3b "Read /…/04_candidates.json and …"` |
| Content in argv? | No (fixes E2BIG) | No |
| Depends on agent tool use/permissions? | No | **Yes** — needs read allowed in headless mode (likely `--auto` or a `permission` block) |
| Context tokens | Same as today | Same |
| Code change | Tiny: `call()` gains `files=[...]` | Small, but riskier |

`opencode run` supports `--file, -f string` and `--auto`. `CLIBridgeClient.call()` currently sets **no `cwd`** on `Popen` and passes **no `--auto`**, so absolute paths plus an explicit permission decision are required for B.

**Recommendation: A.**

## Code changes, in dependency order

**Step 1 — fail loud, no behaviour change (`main_app/api_client.py`).**
In `CLIBridgeClient.call`, before `Popen`, sum the encoded length of every element of `cmd` and raise a clear, actionable error if any single element exceeds 131072 (and, defensively, if the totals approach `ARG_MAX`). The message should name the agent and the offending size. This converts a cryptic `[Errno 7]` into "agent3b-candidate-selector input is 199 186 bytes; the OS limit is 131 072 — move this stage to file input." Do this first so no future overflow is ever misdiagnosed.

**Step 2 — attach support (`main_app/api_client.py`).**
Add `files: Optional[list[str]] = None` to `call()`. In the agent branch, after `--agent`/`-s`, append `['--file', path]` for each entry, then `cmd.append(user)` as now. The legacy branch keeps `system + "\n\n---\n\n" + user` (those evaluation/extractor calls carry small system prompts and are not at risk, but they should also pass through the new guard). Confirm empirically that `--file` is repeatable and how opencode renders the attachment header, because the app's short instruction should name what each attachment is ("the attached file is the candidate pool, indexed by slot").

**Step 3 — workspace module (new `main_app/run_workspace.py`).**
Small, dependency-free helpers: `new_run() -> Path`, `write(run, name, data) -> Path` (accepts `str` or JSON-serialisable), `write_text`, `cleanup(run)`, and `runs_root()` honouring `~/.quiz_app`. Use atomic writes and absolute paths. This is the single place that knows the layout, so nothing else needs to.

**Step 4 — retain library paths (`main_app/library_scanner.py`).**
Add `question_bank_path`, `answer_bank_path`, `concept_block_path` to the dict that `load_topic_files` returns (they are already available on `TopicInfo`). Keep the existing content fields so nothing else breaks.

**Step 5 — convert stages, one at a time, each independently testable.**
For each builder, split it into a short instruction string plus a list of artifacts, write the artifacts with `run_workspace`, and call the client with `files=[...]`. Convert in risk order: **3b first** (the actual failure), then **2a** (next at risk), then 2c, 4a, 5b, 5c, then the sim and option call sites. Each conversion is a self-contained change to one builder plus its call site.

**Step 6 — keep the config manifests.**
`config.save_quota_manifest`, `save_query_spec_manifest`, `save_selected_items`, `save_sequenced_quiz`, and `save_compliance_audit` stay exactly as they are — the UI and the resumable-session logic depend on them. The run files are an *additional* durable copy, not a replacement. Do not delete the config keys.

## What not to do

- Do not have the agents write the authoritative output files. Keep outputs inline and let the app persist them. If an agent writes its own output, you inherit an entire new failure mode (partial writes, malformed JSON, wrong path) with no validation checkpoint. The app is the author of record; the agent only proposes JSON.
- Do not clean up a run directory while a call is in flight. The 3b call and the serial sim/option loops will still be reading their attachments.
- Do not pass relative paths. There is no `cwd` on `Popen`.
- Do not assume `--file` reduces token pressure. It reduces *argv* pressure. If you later want cheaper contexts, that is Option B (agent reads on demand), and it is a separate project.

## Verification

The acceptance test is mechanical and does not need the model:

1. **Unit — argv guard.** Construct each stage's message with the live selection and assert every element is under 131072; assert the guard raises for a synthetic 200 KB element.
2. **Unit — argv shape.** Assert the built command for an agent call is `['opencode','run','--format','json','--agent',<name>, '--file',<p1>, '--file',<p2>, <short>]` and that no element contains the candidate text or concept-block JSON.
3. **Unit — workspace.** Assert `04_candidates.json` and `01_reports.json` are written with the expected sizes and are valid JSON.
4. **Integration — end to end.** Run a real generation over the five maths topics. Success criteria: all stages complete, `~/.quiz_app/runs/<run_id>/` contains the artifacts, and generation no longer dies at 3b.
5. **Regression — parse/validate.** The `_extract_json`, `_parse_3b_selections`, `_parse_5b_verdict`, `validate_*` paths are untouched and their tests must still pass.

## The one-sentence handoff

Bulk inputs move out of `argv` and into a per-run directory at `~/.quiz_app/runs/<run_id>/`, delivered to agents with repeated `opencode run --file` flags; agents keep returning small inline JSON that the app validates and persists; a size guard in `CLIBridgeClient.call` makes any future overflow fail loudly instead of cryptically. Convert 3b first, then 2a, one builder at a time.
