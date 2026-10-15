# Quiz App Developer README

## Overview

This project is a desktop quiz application. The product surface is an **Electron
desktop app** (`desktop/`) that talks to a local **FastAPI sidecar** (`main_app/`).
It lets a user:

- choose a learning library from the local data folders under `X/`
- chat with the diagnosis agents, which slowly build a learner profile
- generate quiz questions from selected topics
- answer questions and receive AI-assisted evaluation
- review past quizzes, resume attempts, and tutor through specific questions

There is no Tkinter UI: the Python package is a headless sidecar, and all user
interface lives in the Electron renderer.

## Project Structure

- `desktop/` — Electron shell (main process in `desktop/src/main`, React renderer in `desktop/src/renderer`)
- `main_app/sidecar/` — FastAPI app the Electron shell spawns (`python -m main_app.sidecar`)
- `main_app/quiz_service.py` — generation orchestration used by the sidecar
- `main_app/agent_runner.py` — agents, sessions, and the learner profile
- `main_app/config.py` — persisted app configuration (`~/.quiz_app/config.json`)
- `main_app/library_scanner.py` — library tree scanning and topic selection
- `main_app/file_retriever.py` — question-bank tag index and candidate retrieval
- `main_app/quiz_instance.py` / `main_app/quiz_note.py` — attempts and quiz notes
- `X/` — learning content and topic folders used by the app
- `tests/` — pytest suite

## Requirements

- Python 3.10+
- Node.js + npm (for the Electron desktop app)
- Python packages from `requirements.txt` (`fastapi`, `uvicorn`, `requests`)
- Optional: `opencode` on your PATH if you use CLI bridge mode instead of direct API calls

### Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cd desktop
npm install
```

## Running the App

Launch the desktop app (builds the renderer, then starts Electron, which spawns
the sidecar):

```bash
./desktop/run-studykit.sh
```

For renderer development with hot reload:

```bash
cd desktop
npm run dev
```

You can also run the sidecar on its own for API work:

```bash
python -m main_app.sidecar
```

## Configuration

The app stores configuration in:

```bash
~/.quiz_app/config.json
```

Key settings include:

- API provider credentials and model names
- selected learning library root
- selected topic folders
- evaluation defaults
- provider mode (`api` or `cli_bridge`)

### Config durability

`config.py` writes the config **atomically** (temp file + `os.replace`) under a
thread lock and a cross-process `flock`, and refreshes `config.json.bak` on every
save. If the live file is ever unreadable it is quarantined to
`config.corrupt-<timestamp>.json` and the last-known-good backup is restored —
so a torn read can never quietly wipe the file down to a single key.

Two kinds of state live in this file and must not be conflated:

- **Pre-quiz chat session** — `agent_sessions` and `pending_messages` for the
  five chat agents (main chat `pre-quiz_main_chat` + the four background models
  `knowledge-graph-builder`, `misconception-classifier`, `mechanism-evaluator`,
  `drill-recommender`). They share one lifetime: persisted across app restarts
  so a chat can be continued, and reset together by `clear_sessions()` for a
  brand-new chat. This is *not* a durable learner profile.
- **Run-scoped manifests** — `quota_manifest`, `query_spec_manifest`,
  `selected_items`, `sequenced_quiz`, `compliance_audit`. Disposable per
  generation run.

The quiz store (`~/.quiz_app/instances/`, artifacts, history) is separate and is
never touched by chat-session management.

### Continuing a chat

The Quiz start screen offers **Start new chat** (`POST /api/quiz/chat/new` →
resets the five agents) and **Continue last session** (`GET /api/quiz/chat/session`
tells the UI whether one exists). Continuing never reopens a generated quiz. The
first-turn-vs-continuation decision is made from whether a main-chat session id
already exists — not from the client transcript, which is not stored.

## Development Notes

### Generation guard

A quiz cannot be generated without at least one selected topic. The sidecar
returns HTTP 400 and `QuizService.generate_quiz()` fails fast with
`NO_TOPICS_ERROR` before any agent runs — this replaced an opaque
"empty selected-items list" failure that only appeared deep in the sequencer.

### API provider behavior

The app supports:

- direct API access via GROQ/OpenRouter/custom OpenAI-compatible endpoints
- CLI bridge mode via `opencode`

When using CLI bridge mode, the app depends on `opencode` being installed and
available in your PATH.

### Library data format

The quiz content is expected to live under folders such as:

```text
X/<subject>/<topic>/
```

with files such as:

- `question_bank.txt`
- `answer_bank.txt`
- `concept_block.json` (optional)
- `simulations/<sim_name>/README.md` (optional)

## Troubleshooting

- If the sidecar fails to start, check `~/.config/<app>/sidecar.log` (or the repo
  root `sidecar.log`) for the spawn output.
- If API calls fail, verify your provider keys or switch to CLI bridge mode.
- If topics do not appear in the library selection view, confirm the folder
  structure under `X/` matches the expected subject/topic layout.
- If generation reports "No topics selected", re-select topics in Settings, then
  check `load_selected_topics` warnings in the sidecar log for paths that no
  longer resolve.

## Useful Development Commands

```bash
# desktop app
./desktop/run-studykit.sh

# sidecar only
python -m main_app.sidecar

# tests
python -m pytest tests
```
