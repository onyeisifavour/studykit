# Dashboard Data Population Log

**Date:** 2026-08-11
**Status:** Dashboard readability fixed via heuristic classifier — deeper rework of data population TBD by user.

---

## Summary

The Electron Dashboard (`desktop/`) displays data computed by `main_app/dashboard_stats.py::build_dashboard()`,
served by the FastAPI sidecar (`main_app/sidecar/app.py`, `GET /api/dashboard`). The dashboard **does not read
the user's selected topic folders directly** — it reads quiz logs in `~/.quiz_app/logs/quiz_*.json` and groups
per-question credit by the **topic string the AI assigned to each question**.

## How the dashboard data is populated (end-to-end)

1. **Selection (Settings):** user scans the library and checks topic folders. Folder paths are saved as
   `selected_topics` in `~/.quiz_app/config.json` (`main_app/config.py:89`).
2. **Quiz start (`main_app/ui/quiz_page.py:227`):** `_start_new_session()` reads `selected_topics` and
   `library_scanner.load_selected_topics()` (`library_scanner.py:223`) loads each folder's files — question
   bank, answer bank, concept blocks, sim readmes — merged into the AI prompt context.
3. **AI names the topics:** the agent generates a blueprint (`Q01 | TYPE | SECTION | TOPIC | ...`). The TOPIC
   column is whatever the AI calls it — folder name, concept title, or its own wording. This is the source of
   both useful names (`SI Units - Base Units and Redefinition`) and junk (`topicfolder1`).
4. **Bank override (`question_generator.py:349`):** when a real question is matched from the question bank,
   the bank entry's topic metadata replaces the blueprint label (unless `unknown`). No match (e.g. physics
   folders without answer banks) → blueprint label survives.
5. **Logging (`quiz_page.py:702`):** each `QuestionRecord` stores its `topic` (`session_log.py:55`); quiz-level
   `topics` = distinct topics seen (`quiz_page.py:694`).
6. **Dashboard (`dashboard_stats.py`):**
   - `subjects` — buckets each *question*'s credit by subject via `_question_subject()`; most-weighted first.
   - `weak_topics` — per-topic pct < `WEAK_TOPIC_THRESHOLD_PCT` (60), weakest first, cap `WEAK_TOPIC_LIMIT` (4).
   - `recent` — newest `RECENT_LIMIT` (5) quizzes; topic = `topics[0]`, plus MC score / written pct / skipped.
   - `avg_pct` — **mean of per-quiz overalls**, not an all-questions aggregate.
   - `setup_needed` — no `selected_topics` and no `library_root` in config.

## What changed this session (readability fix)

- `dashboard_stats.py`:
  - `_subject_of()` — rich keyword table (`si unit`, `physic`, `math`, `dimensional analysis`, ...), `Subject (Topic)`
    prefix parsing, `:` split, else `Other` (never the raw topic — this produced the junk subject rows).
  - `_clean_topic()` — strips `Mathematics (Base Conversion)` → `Base Conversion` for display.
  - `_is_garbage_topic()` — filters leaked folder names (`topicfolder\d*`, `untitled`, ...); their credit still
    counts toward subjects via `_question_subject()` quiz-topic fallback.
  - `_group_buckets()` — key functions now receive `(log, q)`.
- `desktop/src/renderer/screens/Dashboard.tsx` — `shortTopic()` mirrors `_clean_topic()` (duplication, see Open Issues);
  `title` tooltip carries the full topic.
- `desktop/src/renderer/styles/global.css` — truncation guardrails so text can never push layout out of place:
  `.subj-name` flexible max-width + ellipsis, `.subj-track` `min-width:0`, `.weak-topic` 2-line clamp,
  `.act-topic` ellipsis, `.act-date/-score/-tags` nowrap.
- Result on real logs: subjects `Physics 6% / Mathematics 0%` (was 6 rows incl. `topicfolder1`); weak topics
  clean and uniform-height; recent activity readable; no horizontal scroll.

## Open Issues / Remaining Work

### 1. Root cause: AI-assigned topic labels are unreliable (main rework target)
The heuristic classifier is a stopgap. The real fix is upstream: record canonical metadata at log time.
- Add explicit `subject`/`topic`/`source` fields to `QuestionRecord` (from `library_scanner._scan_topic`:
  folder parent = subject, folder name = topic), falling back to the AI label only when no bank match exists.
- Persist a `quiz_id` → selected-folder mapping so logs are self-describing.
- `topicfolder1` persists because physics `L1.1`–`L1.5` folders have question banks but **no answer banks**
  (`QUESTION_BANK_POPULATION_LOG.md` issue 2) → no match → blueprint label survives.

### 2. Renderer duplicates backend cleaning
`shortTopic()` in `Dashboard.tsx` re-implements `_clean_topic()`. Have the backend send cleaned labels.

### 3. `avg_pct` is mean-of-per-quiz-average
Small quizzes weigh equally with large ones (explains the odd 8% vs subject 6%/0%). Consider an all-questions
aggregate (total credit / total weight).

### 4. Recent activity shows only `topics[0]`
Multi-folder quizzes show one of several topics. Consider a compact multi-topic or subject list.

### 5. Thresholds hardcoded
`WEAK_TOPIC_THRESHOLD_PCT=60`, `WEAK_TOPIC_LIMIT=4`, `RECENT_LIMIT=5` — consider config-driven.

### 6. No time dimension
No last-7-days filter, no trends, no per-day history.

### 7. `Other` bucket can still appear
When neither question nor quiz-level topics classify (rare). Decide whether to show or hide it.

---

## Next Direction

User will rework data population. The log above documents current behavior and the gap list to target.
