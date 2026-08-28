# AI Workflow Handoff for Developers

## Purpose

This document is a practical handoff for anyone who needs to understand, debug, or extend the AI-driven quiz workflow in this app.

The app is not a simple one-shot chatbot. It runs a multi-stage pipeline that combines:

- a Tkinter front end
- a local topic library under X/
- AI agents invoked through the opencode CLI bridge
- parsing and validation layers that turn raw AI responses into structured quiz data

If you are trying to understand how the app “thinks,” this is the map to follow.

---

## 1. High-level flow

The workflow is centered around the quiz experience and roughly follows this path:

1. User opens the Quiz page and enters the chat stage.
2. The app loads selected topic folders from the local library.
3. The pre-quiz chat uses the main chat agent.
4. Background models analyze the topic context and produce reports.
5. A quota planner agent turns those reports + user intent into a structured quota manifest.
6. A topic resolver and fallback builder convert that plan into file query specs.
7. The app retrieves candidate questions from the bank.
8. A blueprint is generated and parsed.
9. Non-sim and sim questions are assembled into a final quiz question list.
10. The quiz runs, and answers can be evaluated or summarized by AI.

In short: chat -> reports -> plan -> retrieve -> build -> quiz -> evaluate.

---

## 2. Main entry points

### UI entry
- [main_app/ui/quiz_page.py](main_app/ui/quiz_page.py)

This is the main orchestrator for the quiz lifecycle. It owns the state machine:

- CHAT
- THINK
- LOAD
- QUIZ
- DONE

It decides which screen is shown, handles back/cancel behavior, and launches the relevant pipeline phases.

### App bootstrap
- [main_app/app.py](main_app/app.py)
- [main_app/__main__.py](main_app/__main__.py)

These are the startup layers. The app is launched from the module entry point and then boots the Tkinter window.

### Settings and provider wiring
- [main_app/ui/main_window.py](main_app/ui/main_window.py)
- [main_app/config.py](main_app/config.py)
- [main_app/api_client.py](main_app/api_client.py)

These files control how the app connects to AI providers and whether it uses direct API calls or the CLI bridge.

---

## 3. The AI execution stack

### A. Chat and background report generation
Primary file:
- [main_app/agent_runner.py](main_app/agent_runner.py)

This is the central AI runner. It manages:

- main chat calls
- background model calls
- session persistence per agent
- pending/retry behavior for network issues
- the later quota-planner and query-specifier pipeline

Key agent names used by the app include:

- pre-quiz_main_chat
- diagnostic-quota-planner
- agent2a-topic-resolver
- agent2c-fallback-builder
- knowledge-graph-builder
- mechanism-evaluator
- misconception-classifier
- drill-recommender

Important detail: the app uses the opencode CLI bridge, not direct prompt calls for the agent-driven workflow. That means the app depends on the local opencode setup being available and the agents being registered.

### B. API client layer
- [main_app/api_client.py](main_app/api_client.py)

This file handles low-level model calls. It supports:

- direct HTTP API calls for GROQ/OpenRouter/custom providers
- a CLI bridge client for opencode

The CLI bridge client is the crucial piece for the agent workflow.

### C. Quiz evaluation and tutoring
- [main_app/evaluation_runner.py](main_app/evaluation_runner.py)

This file bridges the AI into the quiz runtime. It covers:

- pre-quiz chat
- live evaluation during the quiz
- batch evaluation at the end
- summary report generation
- tutoring thread responses after the quiz

If a bug appears in AI feedback, summary text, or tutor replies, this is one of the first modules to inspect.

---

## 4. The workflow in order

### Stage 1: Chat setup
Triggered from:
- [main_app/ui/quiz_page.py](main_app/ui/quiz_page.py)

Flow:
- selected topics are loaded from the local library
- the chat screen is shown
- the user talks about the exam goal, topic focus, and question preferences

The main chat agent is called from [main_app/agent_runner.py](main_app/agent_runner.py).

### Stage 2: Background analysis
Also driven by [main_app/agent_runner.py](main_app/agent_runner.py).

The app sends the student’s message to four background agents:

- knowledge graph builder
- misconception classifier
- mechanism evaluator
- drill recommender

These reports are collected and later used by the quota planner.

### Stage 3: Quota planning
Handled by the quota planner agent in [main_app/agent_runner.py](main_app/agent_runner.py).

This step converts the user request and the background reports into a structured manifest that describes:

- question count
- slot allocations
- flaw priorities
- topic emphasis
- style constraints

The manifest is validated before the next stage continues.

### Stage 4: Agent 2 query specification
Still in [main_app/agent_runner.py](main_app/agent_runner.py).

This is the “AI workflow” part that resolves the abstract plan into real bank queries.

It runs a two-step sequence:

1. topic resolver agent
2. fallback builder agent

The code also performs tag mapping locally before the fallback builder is called.

This stage produces a file query spec manifest that says which subject/topic/type/format combinations should be searched.

### Stage 5: Candidate retrieval
- [main_app/file_retriever.py](main_app/file_retriever.py)

This layer takes the manifest and the loaded topic files, then retrieves candidate questions from the available question banks.

The retrieval logic is important because it determines what the downstream AI sees as its pool of possible questions.

### Stage 6: Agent 3 candidate selection
- [main_app/agent_runner.py](main_app/agent_runner.py) (`call_candidate_selector`)
- [agent3b_candidate_selector.md](agent3b_candidate_selector.md)
- [main_app/manifest_validator.py](main_app/manifest_validator.py) (`validate_selected_items`)

New step wired into the pipeline (live-verified 2026-08-05). After candidate
retrieval, the app groups the pool per slot:

- 0 candidates → slot flagged `MISSING_BANK_ITEM`
- 1 candidate → auto-selected by code
- 2+ candidates → the `agent3b-candidate-selector` agent judges which candidate
  fits the slot objective (returns `selections` keyed by local
  `candidate_index`)

A selected-items manifest is assembled and validated, then handed to the quiz
page. The quiz page now runs Agent 4 on it (Stage 6b below); the legacy
blueprint flow remains only as a fallback when the agent runner is unavailable.

### Stage 6b: Agent 4 pedagogical sequencing
- [main_app/sequencer.py](main_app/sequencer.py) (deterministic 4b–4d)
- [main_app/agent_runner.py](main_app/agent_runner.py) (`call_sequencer`)
- [agent4a_pacing_arc.md](agent4a_pacing_arc.md)
- [main_app/manifest_validator.py](main_app/manifest_validator.py) (`validate_sequenced_quiz`)
- [main_app/question_generator.py](main_app/question_generator.py) (`build_questions_from_sequence`)

Wired into the pipeline (live-verified 2026-08-05). After Agent 3, the app
runs the Agent 4 split pipeline:

- 4a: the `agent4a-pacing-arc` agent chooses the pacing arc template
  (Repair First / Ramp Up / Balanced) — the only AI judgment step
- 4b: code buckets items by objective type → pacing stage and sorts within
  each stage by match confidence
- 4c: code picks the most approachable item as the warm-up Gateway (position 1)
  and keeps same-topic / same-sim-set items consecutive
- 4d: code assigns `sequence_index` / `pacing_stage` / `position_rationale`,
  validates, persists, and hands the sequenced manifest to Agent 5

The quiz page converts the manifest straight into the playable question list
via `build_questions_from_sequence` (no re-sort), then logs and starts the quiz.
The sequencing manifest is config-stored (like `query_spec_manifest`); full
question text stays in memory (Issue #8 pattern).

### Stage 6c: Agent 5 compliance audit
- [main_app/compliance_auditor.py](main_app/compliance_auditor.py) (Steps 1 + 4)
- [main_app/agent_runner.py](main_app/agent_runner.py) (`call_compliance_audit`)
- [agent5b_diagnostic_audit.md](agent5b_diagnostic_audit.md)
- [agent5c_preference_audit.md](agent5c_preference_audit.md)

Final gatekeeper between the pipeline and the Quiz UI (live-verified
2026-08-05). After Agent 4:

- Step 1 (code): structural & integrity audit — length, unique items, field
  integrity, tag consistency, sim-set contiguity.
- Steps 2/3 (parallel): `agent5b-diagnostic-audit` checks diagnostic coverage;
  `agent5c-preference-audit` checks the user's explicit request. Independent
  inputs, run concurrently.
- Step 4 (code): decision gate. PASSED → sanitised payload (pacing metadata
  kept); FAILED → one automatic retry of the AI audits, then the failure +
  targeted rebuild directive is surfaced to the user.

The quiz starts only from the audited payload (`_on_audit_ready` →
`_start_quiz_from_sequence`). The audit result is config-stored
(`compliance_audit`); the full payload stays in memory.

### Stage 7: Blueprint generation
- [main_app/blueprint_generator.py](main_app/blueprint_generator.py)

The blueprint is a structured plan for the quiz. It describes which question slots are:

- MCQ or subjective
- simulation or non-simulation
- associated with a topic

This is parsed from an AI response and then later used to organize the actual question content.

### Stage 8: Question generation and answer matching
- [main_app/question_generator.py](main_app/question_generator.py)
- [main_app/answer_matcher.py](main_app/answer_matcher.py)

This is where the app turns the blueprint and retrieved questions into the final quiz content.

Key behaviors:

- non-sim questions are filled from matched bank content
- sim questions are filled from simulation sets when present
- MCQ options are parsed and cleaned
- the final list is assembled in order for the actual quiz UI

### Stage 9: Quiz runtime and evaluation
- [main_app/ui/quiz_page.py](main_app/ui/quiz_page.py)
- [main_app/evaluation_runner.py](main_app/evaluation_runner.py)

This is the runtime surface where the generated quiz is shown to the student. It also triggers:

- live evaluation
- batch evaluation
- summary generation
- tutoring follow-up

---

## 5. Where to look when debugging

### If the app fails before the quiz starts
Inspect:
- [main_app/ui/quiz_page.py](main_app/ui/quiz_page.py)
- [main_app/agent_runner.py](main_app/agent_runner.py)
- [main_app/config.py](main_app/config.py)

Common issues:
- no topics selected
- opencode not installed
- agents not registered in the opencode config
- bad topic folder structure under X/

### If the main chat is not responding
Inspect:
- [main_app/agent_runner.py](main_app/agent_runner.py)
- [main_app/api_client.py](main_app/api_client.py)

Check:
- whether the CLI bridge client is active
- whether the main chat agent is registered
- whether session persistence is interfering

### If the blueprint looks wrong
Inspect:
- [main_app/blueprint_generator.py](main_app/blueprint_generator.py)
- [main_app/question_generator.py](main_app/question_generator.py)

The app assumes very specific AI response formats. If the model output changes, the parsers may silently skip content.

### If the candidate pool is empty or wrong
Inspect:
- [main_app/agent_runner.py](main_app/agent_runner.py)
- [main_app/file_retriever.py](main_app/file_retriever.py)
- [main_app/answer_matcher.py](main_app/answer_matcher.py)

This is often where the “AI planning looked correct but the actual questions were bad” problem shows up.

### If evaluation or tutor replies are wrong
Inspect:
- [main_app/evaluation_runner.py](main_app/evaluation_runner.py)
- [main_app/prompts.py](main_app/prompts.py)
- [main_app/score_parser.py](main_app/score_parser.py)

This is where answer scoring and explanation formatting are handled.

---

## 6. Important assumptions and constraints

### The AI workflow depends on opencode
The agent-driven workflow does not work unless the opencode CLI bridge is available and the relevant agents are registered.

### The app expects structured AI output
Several parsers assume a fairly stable output shape. If the model output drifts, parsing will fail or silently degrade.

### Topic data is local and folder-based
The app relies on local content under X/ and expects it to be organized in a recognizable subject/topic structure.

### The UI is asynchronous
Many AI calls run in the background and update the Tkinter UI through callback plumbing. This means UI bugs can be caused by race conditions or thread-safety issues.

---

## 7. Recommended investigation order

If you are new to this codebase, the fastest path is:

1. Read [main_app/ui/quiz_page.py](main_app/ui/quiz_page.py) to see when the workflow starts.
2. Read [main_app/agent_runner.py](main_app/agent_runner.py) to see how the agents are invoked and persisted.
3. Read [main_app/file_retriever.py](main_app/file_retriever.py) and [main_app/question_generator.py](main_app/question_generator.py) to understand how the AI output becomes quiz content.
4. Read [main_app/evaluation_runner.py](main_app/evaluation_runner.py) to see how AI is used during and after the quiz.
5. Then inspect [main_app/api_client.py](main_app/api_client.py) for provider wiring and transport details.

---

## 8. Useful local debugging notes

### Run the app
From the project root:

```bash
python -m main_app
```

### Check the agent registration state
The app checks registered agents by reading the local opencode config. If agents are missing, the workflow will fail later in a confusing way.

### Watch for validation failures
The workflow has validation layers around the quota manifest and query spec manifest. These are often the first place to inspect when the pipeline stops mid-way.

---

## 9. Open-ended areas to explore

If you want to improve the AI workflow next, the most promising areas are:

- improving the reliability of agent response parsing
- making the fallback logic more robust when no bank questions match
- tighten validation around blueprint and question-generation outputs
- make the workflow more observable with richer logging
- reduce the dependency on fragile prompt formatting and make it more deterministic

---

## 10. Short version

If you only remember one thing: the AI workflow is orchestrated by [main_app/agent_runner.py](main_app/agent_runner.py), the quiz lifecycle is coordinated by [main_app/ui/quiz_page.py](main_app/ui/quiz_page.py), and the transformation from AI output into actual questions happens in [main_app/file_retriever.py](main_app/file_retriever.py), [main_app/blueprint_generator.py](main_app/blueprint_generator.py), and [main_app/question_generator.py](main_app/question_generator.py).
