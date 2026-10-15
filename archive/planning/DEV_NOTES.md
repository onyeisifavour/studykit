# Changes & Improvements — StudyKit Quiz App

## Files Modified
- `main_app/config.py`
- `main_app/api_client.py`
- `main_app/ui/main_window.py`

No other files were changed. All modifications are backward-compatible.

---

## 1. Custom API Provider (OpenAI-compatible)

**config.py** — added three keys:
- `custom_api_url` — base URL for any OpenAI-compatible endpoint
- `custom_api_key` — API key
- `custom_model` — model name

**api_client.py** — `Credential` dataclass gained a `url` field. Custom provider appends `/chat/completions` to the URL if not already present. It's the 3rd credential in the failover chain (after all GROQ, then all OpenRouter keys).

**main_window.py** — Settings page has a new "CUSTOM (OpenAI-compatible)" section below GROQ/OpenRouter with URL, Key, and Model fields. Saved/loaded with existing key config.

---

## 2. CLI Bridge Mode (opencode)

Replaces direct API calls with a local `opencode` CLI subprocess. Zero key management — inherits the user's terminal login and credits.

**config.py** — added two keys:
- `provider_mode` — `"api"` (default) or `"cli_bridge"`
- `cli_model` — model name (default: `opencode/big-pickle`)

**api_client.py** — new `CLIBridgeClient` class with the same `call()` interface as `ApiClient` (drop-in replacement). Key details:
- Uses a **pseudo-terminal (PTY)** because opencode requires TTY to output full responses
- Uses **non-blocking `os.read`** with `fcntl` because `select.select` doesn't work reliably in daemon threads
- Parses `--format json` output — text arrives in `event["part"]["text"]` fields
- Runs in a daemon thread, same as `ApiClient`

**main_window.py** — Settings page now has a "PROVIDER MODE" toggle at the top:
- **API (Direct)** — shows GROQ/OpenRouter/Custom key fields
- **CLI Bridge (opencode)** — shows only a model name field
- Switching modes live-swaps the active client on `EvaluationRunner` and `QuizPage` via `_sync_client_to_mode()`

---

## How to Run
```bash
cd ~/Desktop/Learning/Resources/virtuals_and_code/quiz_app
python -m main_app
```
Requires `opencode` to be installed and in PATH for CLI Bridge mode.

---

## Testing Notes
- Test topic folder: `X/physics/topic_folder_2/` (has question_bank.txt, answer_bank.txt, concept_block.json, simulations/)
- `X/topic_folder_1/` is at wrong nesting depth (directly under X/, needs X/Subject/Topic/)
