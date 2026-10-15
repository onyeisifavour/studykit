# StudyKit — UI/UX Designer Handoff

**Goal:** Rebuild the StudyKit shell as an **Electron application with a fresh,
web-based UI**. All Python backend logic is preserved; only the shell changes.

**Status:** v0.2 (Tkinter) → Electron redesign. This document is the source of
truth for the designer. Every screen, state, string, and data shape below was
derived from the actual running code (`main_app/`), not from assumptions.

**Key product fact:** StudyKit is a diagnostic-driven quiz generator. A 5-agent
AI pipeline (chat → quota plan → query spec → candidate selection → sequencing →
compliance audit) turns a conversation with the student into a *paced* quiz.
The redesign must surface that pipeline as a first-class, reassuring experience,
not hide it.

---

## 1. Product & design context

### What StudyKit is
- A student opens a chat, tells the AI what to study, and gets a generated quiz
  (MCQ + written questions, some backed by external simulations) with live or
  end-of-quiz AI evaluation.
- Past quizzes are reviewable, and each question can be opened in a tutoring
  thread.
- **Flashcards** (new) review missed questions from past quizzes and Q&A decks
  from the learning library.
- The learning library is a folder of topics on disk; each topic carries
  `question_bank.txt`, `answer_bank.txt`, optional `concept_block.json` and a
  `simulations/` folder. The user selects topics in Settings.

### Who uses it
Self-directed students preparing for exams (IGCSE/WAEC/IB/AP content in the
library). Single-user desktop app today.

### Design goals
1. **Reduce the cost of the 4–8 minute generation wait.** The pipeline is the
   core product; make progress visible, interruptible, and re-readable
   (peek-at-chat pattern).
2. **Make weak spots the hero.** The pipeline knows *why* each question is asked
   (pacing stage + objective type). Surface progression, not just scores.
3. **Fresh, calm, modern.** Full redesign liberty. Aim for a tool a serious
   student trusts: clear hierarchy, low noise, generous whitespace.
4. **Multi-OS native feel** (Windows / macOS / Linux) via Electron.

### Hard constraints
| # | Constraint | Consequence |
|---|-----------|-------------|
| 1 | All Python logic is kept (`main_app/` untouched in behaviour) | Renderer talks to a **local Python sidecar** (HTTP/WebSocket on localhost); it never calls the AI directly |
| 2 | Math notepad / MathType (LaTeX answer sheet) is a **documented extension slot**, NOT in this prototype | Non-MCQ answers stay a plain text input; design must allow swapping in a LaTeX editor later |
| 3 | Simulations launch as external processes/browser tabs today | Design the "Launch simulation" affordance; an embedded sim pane is a future option |
| 4 | Puter.js runtime API-key retrieval is a future slot | Settings' key section must tolerate becoming optional/auto |
| 5 | App data lives in `~/.quiz_app/` (logs) and a config file | Read-only ingestion; no new persistence in this round |
| 6 | Window baseline 1040×680, min 760×520 | Layout must hold at both sizes; use a 2-pane pattern that degrades gracefully |

### Where the designer has full liberty
- Complete visual language (tokens, type, motion, iconography).
- Information architecture — a **dashboard-first proposal** is in §2, treat it
  as a recommendation you may evolve.
- Interaction details: keyboard, transitions, microcopy, empty/error treatment.
- Any *additive* feature (e.g. richer dashboard widgets, onboarding).

---

## 2. Information architecture

### Current (v0.2) — 5 pages, sidebar rail
`Home` (static greeting + 4 cards) · `Quiz` (chat→pipeline→quiz→report) ·
`Flashcards` (new) · `Review` (past quizzes) · `Tutor` (per-question threads) ·
`Settings`.

### Proposed — dashboard-first
The static Home becomes a **live dashboard** — the memory layer between quizzes
(see §3.2 for the full spec). Rationale: the app currently forgets everything
after a quiz; the dashboard re-uses data the app already stores to make "what
should I do next" obvious.

```
┌──────────────────────────────────────────────────────────────┐
│ ⌂ StudyKit        [⚙ Settings]        v0.2                  │
├───────────────────────────────────────────────────────────────┤
│  Good evening, Favour                                        │
│  7 quizzes · 64 questions · 71% average                      │
│                                        [ Start New Quiz → ]   │
│                                                               │
│  Your subjects                    Needs attention             │
│  ┌─┬─┬─┬─┐                      ┌───────────────────────────┐│
│  │█│█│▓│▓│  Maths 88%           │ Newton's Laws     42%     ││
│  │█│█│▓│▓│  Chem   74%          │ Stoichiometry     48%     ││
│  │█│▓│▓│▓│  Phys   61%          │      [Review] [Tutor]     ││
│  │█│▓│▓│▓│  Econ   55%          └───────────────────────────┘│
│  └─┴─┴─┴─┘                                                 │
│                                                               │
│  Recent activity                                              │
│  ▪ 12 Jul · Newton's Laws · 6/10 · MCQ 3/4 · written 62%      │
│  ▪ 10 Jul · Acids & Bases · 8/10 · 1 skipped                  │
│  ▪ 08 Jul · Kinematics · 4/10 · 2 skipped · incomplete        │
│                          [ View all history → ]               │
└───────────────────────────────────────────────────────────────┘
```

### Mapping (nothing is lost)
| v0.2 page | Dashboard-first destination |
|-----------|------------------------------|
| Home | Dashboard (its action cards become sidebar entries + dashboard CTAs) |
| Quiz | Dedicated **Quiz** workspace (unchanged flow, better pipeline UX) |
| Flashcards | **Flashcards** workspace (unchanged flow) |
| Review | **History** (quiz list → question detail) |
| Tutor | **Tutor** (quiz list → per-question thread) |
| Settings | **Settings** (unchanged sections) |

Recommended nav model: a slim **icon rail** (collapsible to labels), 5–6 items:
Dashboard · Quiz · Flashcards · History · Tutor · Settings.

---

## 3. Screen-by-screen spec

Each screen lists: purpose, entry/exit, states (default / empty / loading /
error), content, and key interactions. **Priority:** P0 = core flow, P1 =
secondary, P2 = polish.

---

### 3.1 App shell — P0
- Window title "StudyKit"; default 1040×680, min 760×520; resizable.
- Persistent left nav rail (collapsible 200px ↔ 58px). Active item indicated
  with an accent bar + tint. Version label pinned at the bottom.
- Content region hosts exactly one page at a time; navigation is stateful
  (pages keep their internal state when you leave and return — e.g. you can be
  mid-chat, visit Settings, come back, and the chat is still there).

**States**
- Default: rail expanded.
- Collapsed: icons only (title/version hidden).
- Active nav item = current page.

---

### 3.2 Dashboard — P0 (new)
Purpose: answer "where am I, what's weak, what next?" in one glance.

**Content (all computed from existing quiz logs + config — a small sidecar
endpoint provides it, see §7):**
1. **Hero line:** greeting ("Good evening"), running totals: `N quizzes ·
   M questions · P% average`.
2. **Primary CTA:** `Start New Quiz →` (dominant, top-right).
3. **Your subjects:** horizontal mastery bars, one per subject (MCQ + written
   accuracy combined, respect skip mode). Color-coded (≥80 green, ≥60 amber,
   <60 red).
4. **Needs attention:** cards for weak topics (questions answered wrong or
   scored <0.5, grouped by topic, with accuracy %). Actions per card:
   `Review` (open that quiz history) and `Tutor` (open a tutoring thread).
5. **Recent activity:** chronological list of quizzes: date · topics · score
   (e.g. `6/10`), skipped count, "incomplete" tag. Rows open Review.
6. **Setup banner** (only when no topics are selected): "Set up your learning
   library →" linking to Settings.

**States**
- Empty (first run, no quizzes): centered empty state "Finish your first quiz
  to see your progress" + `Start New Quiz` CTA + setup CTA.
- Loading: skeleton blocks (not spinners-only).
- Error: quiet inline note, content still renders what it can.

---

### 3.3 Quiz workspace — CHAT state — P0
Purpose: the student tells the AI what to study.

**Layout:** page title + stage badge (top-right) + skip-mode toggle row + chat.

1. **Stage badge** (live status of the whole quiz lifecycle). States + colors:
   - `CHAT` blue · `PLANNING` amber · `GENERATING` amber · `SEQUENCING` amber ·
     `AUDITING` amber · `Q n / N` blue · `REPORT` green · `SETUP NEEDED` red.
2. **Skip-mode toggle:** a segmented control — `If I skip a question:`
   `Count as 0` | `Exclude from score`. Label reflects the selected choice.
   (Design as two radio-like chips; must be re-usable on other surfaces.)
3. **Chat:**
   - Header "Let's plan your quiz" + one-line hint.
   - Pre-greeting: centered `Start Chat` button.
   - Post-greeting: message list (user bubbles right/accent, AI bubbles left/
     neutral) + input row (`Enter` sends) + `Send`; a `Generate Quiz →`
     button pinned at the right of the input row, always available once chat
     has started.
   - While the AI is typing: send button morphs to "…".
   - AI messages may contain Markdown-ish math (LaTeX `$…$`) — render friendly
     or collapse cleanly. **Design a safe fallback for raw LaTeX.**

**States:** idle (Start Chat) · waiting (… ) · ready (input enabled).

---

### 3.4 Quiz workspace — PIPELINE PROGRESS — P0
Purpose: be honest about the 4–8 min generation wait and make it comfortable.

The pipeline is **6 sequential stages**: `chat → quota planning → query
specification → candidate selection → sequencing → compliance audit`, then the
quiz appears. The current app shows only a generic "Designing your quiz
blueprint…". **The redesign should visualize stage progress** — a stepper, a
progress line with current-stage label + subtle detail, or a log. Stage names
should be plain-English, not agent names.

**Controls during pipeline (non-blocking):**
- `← Back to Chat` (peek): reveals the chat transcript WITHOUT cancelling.
  A sticky banner at the bottom of the chat shows live progress text
  (`Still sequencing your questions…`) + `Continue →` to return to the
  progress view.
- `✕ Cancel`: aborts the in-flight stage. Shows a **Cancelled** screen with
  `Retry →` (re-runs only that stage) and `← Back to Chat instead`.

**States:** loading (progress stepper + message) · peek (chat + banner) ·
cancelled (retry) · failed (see §3.5).

---

### 3.5 Error surfaces — P0
- **Stage error:** title `Something went wrong during {stage}.` + readable
  message + `← Back to Chat`. (Pipeline failures carry a targeted rebuild
  directive from the audit gate; surface the *human* part, keep details
  expandable.)
- **Setup needed:** "No topics selected yet." + "Go to Settings, scan your
  learning library, and select at least one topic…" + `Open Settings →`.
- **Global crash guard:** any unhandled exception shows an error dialog
  ("Unexpected error … details were printed to the terminal") instead of dying.
  Keep this safety net; restyle it.

---

### 3.6 Quiz workspace — QUIZ state — P0
Purpose: answer questions one at a time with immediate (or deferred) feedback.

**Layout:** two panes with a draggable divider.
- **Left (question + answer):**
  1. **Simulation banner** (only for sim questions): amber card
     `🧪 SIMULATION REQUIRED` + instruction + `▶ Launch Simulation` (opens the
     external sim). 
  2. **Question card:** accent top bar + question text (readable at 12px+,
     wraps; LaTeX-safe fallback).
  3. `Your answer` label. Input by type:
     - **MCQ:** vertical option list (radio-style rows, full-width clickable).
     - **Written (Theory/Hybrid):** multiline text box. *(Design note: this is
       the MathType extension slot — keep the region self-contained so a
       LaTeX notepad can replace it later.)*
     - **MCQ with no options (bank/data glitch):** warning line + free-text
       fallback; the UI must never trap the student here.
  4. **Action row:** `Submit Answer` (primary) · `Skip →` (secondary) · on the
     far right `■ End & Get Report` (danger, always available).
- **Right (Feedback panel — visually distinct, current code uses the dark
  sidebar colour):**
  1. Header `Feedback` + a mode line: "Live evaluation ON — feedback appears
     after each written answer." / "Evaluation OFF — written answers are scored
     at the end."
  2. **Verdict** line: `✓ Correct` (green) / `✗ Incorrect` (red) / `Score:
     0.83` (green ≥0.5 else red) / `Answer recorded` (neutral) / `Evaluating…`
     / `Evaluation failed`.
  3. AI **feedback** text.
  4. `Next Question →` (appears only after an answer is submitted/skipped).

**States per question:** pristine → (MCQ: selected) → submitted/correct ·
submitted/incorrect · (written: evaluating → scored) · skipped · evaluation-
failed. **Submit requires a non-empty answer**; empty submit prompts "Please
select an option, or use Skip."

**Progression idea (P1):** show pacing stage (Warm-up → Prerequisite Repair →
Core Concept Gap → Transfer/Elevation) as a subtle progress marker, since the
sequencer guarantees this ordering.

---

### 3.7 Quiz workspace — REPORT state — P0
- Stage badge `REPORT` (green).
- **Stats row:** `MCQ: {correct}/{total}` · `Written: {pct}%` · skip-mode note
  in parentheses.
- **Summary report:** the AI's narrative in a scrollable panel. Generated
  after scoring; if generation fails, still show stats + an inline error
  ("⚠ Summary generation failed: …").
- **Actions:** `Start New Quiz` · `Review This Quiz →` (deep-link to History).

---

### 3.8 History (Review) — P0
Two levels:
1. **Quiz list:** scrollable rows — title (topics) + `date • Completed |
   Incomplete`. Empty state: "No completed quizzes yet."
2. **Question detail:**
   - Left rail `QUESTIONS`: one row per question with a **status mark**
     (⊘ skipped / ✓ green / ✗ red / • unanswered / `0.8` score).
   - Right pane: `Question {n} • {topic}`, sim banner if any, question card,
     then per type:
     - **MCQ:** options colored — green = correct, red = your wrong pick,
       suffix labels `← your answer` / `✓ correct`.
     - **Written:** sections `YOUR ANSWER` / `STANDARD ANSWER` / `SCORE` /
       `AI FEEDBACK`.
   - `← All Quizzes` back affordance in the header.

---

### 3.9 Tutor — P0
Purpose: focused per-question tutoring threads.

- Level 1 = History quiz list.
- Level 2 = split view: left = question list (Qn + text preview); right =
  **context card** (Question n, question, your answer, standard answer) + a
  chat pane + input row (`Send`).
- Each question keeps its **own thread history**; switching questions switches
  threads without losing the other's messages.
- Empty state: "Select a question on the left to start tutoring."

---

### 3.10 Flashcards — P0 (new)
Purpose: spaced-ish review of what was missed + browseable topic decks.

- **Deck list:** two grouped sections —
  `FROM YOUR QUIZZES` (decks built from questions answered wrong / scored <0.5,
  one deck per topic) and `FROM YOUR LIBRARY` (one deck per selected topic from
  its question/answer banks). Rows: deck title + `{subject} • {N} cards`.
- **Study view:** header shows `Card {i} / {N}   ·   Got it: {g}`; a large
  **click-to-flip card** (front = question; back = answer, and for quiz-sourced
  cards also your answer + AI feedback). After flipping, two rating actions:
  `↻ Still learning` (red — card returns to the rotation) and `✓ Got it`
  (green — card advances).
- **Summary:** `Deck complete!` + counts + pass % + `↻ Review again` +
  `All decks →`.
- **Empty state:** explain the two sources ("Finish a quiz or select topics in
  Settings to populate decks.").
- `← All Decks` back affordance.

---

### 3.11 Settings — P1
Sections (keep all of these; redesign the forms):
1. **Provider mode** — segmented `API (Direct)` | `CLI Bridge (opencode)`.
   A one-line description swaps under the toggle. Switching mode updates the
   shared backend client (rest of the app reacts).
   - *API mode:* GROQ (4 keys + model), OpenRouter (4 keys + model), Custom
     OpenAI-compatible (URL / Key / Model), `Save API Keys` + inline
     `✓ Saved — n key(s) active`.
   - *CLI Bridge mode:* a single `Model` field
     (format `provider/model`, e.g. `opencode/big-pickle`) + `Save CLI
     Settings`. *(Puter.js slot: this whole section may become automatic;
     keep it a self-contained form.)*
2. **Learning library** — root path field + `Browse` (folder picker) + `Scan`,
   status line (`✓ Found n valid topic(s) across m subject(s)`); a **tree**
   (subject → topics) with checkbox-style selection; invalid topics flagged
   `⚠ missing files`; `Save Selection` + `✓ n topic(s) selected`.
3. **Question types** — Section A (Objective): `Simulation` / `Non-Simulation`;
   Section B (Theory): same two checkboxes; `Shuffle questions` toggle that
   reveals `Keep simulation questions together` / `Shuffle all questions`.
   At-least-one-type rule enforced with inline message.
4. **Default evaluation mode** — segmented `Evaluation ON` / `Evaluation OFF`
   with an explanation line.

---

## 4. Component inventory

Design tokens → atoms → molecules, so the prototype reuses components:

| Group | Components |
|-------|-----------|
| Navigation | Nav rail (icons + labels + collapse), active indicator, version chip |
| Buttons | Primary / secondary / danger / ghost; text + icon variants; disabled; loading (…) |
| Inputs | Text field (single/multi), segmented control, radio rows, checkboxes, toggle |
| Cards | Deck/quiz/list row, question card, weak-spot card, context card, sim banner |
| Chat | User bubble, AI bubble, typing state, input composer |
| Status | Stage badge, verdict line, inline status (✓/⚠), empty state, skeleton, progress stepper |
| Panels | Feedback panel, question-nav rail, scroll regions |
| Feedback | Toast/inline notice, global error dialog |

Each component must have defined: default / hover / active / disabled /
loading / error appearances, and both light & dark support (see §8).

---

## 5. State matrix (quiz lifecycle)

The backend owns one state machine; the UI must render every combination.

| Backend stage | UI surface | User actions available |
|---------------|------------|------------------------|
| `idle` | Setup-needed or fresh chat | Configure library (Settings) |
| `chat` | Chat | Send message, Generate Quiz, change skip mode |
| `think` (quota planning) | Progress stepper | Back to Chat (peek), Cancel → Retry/Back |
| `load`-like stages (query spec, candidate selection, sequencing, audit) | Progress stepper | Peek / Cancel / Retry |
| `quiz` | Question view | Submit, Skip, End & Get Report |
| `done` | Report | New Quiz, Review This Quiz |

**Cancellation semantics (important):** `Back to Chat` (peek) does NOT cancel
the in-flight call — it keeps running in the background; `Continue` resumes
wherever it actually is. `Cancel` invalidates the call via a generation token;
a stale response is discarded, never rendered. The new UI must preserve this
distinction visually (peek = safe/banner; cancel = destructive/confirm).

**Shuffle preference:** applies at quiz start only, `Keep simulation questions
together` by default.

---

## 6. Content & copy spec

Tone: **warm, capable, non-sycophantic.** Second person, short sentences.
Never blame the student ("No answer was given" not "You didn't answer").

### Key strings to preserve (or improve, keeping meaning)
- Chat: "Let's plan your quiz" · "Tell the AI what topics, how many questions,
  and any weak areas to prioritise." · "Start Chat" · "Generate Quiz →" ·
  "Send"
- Skip mode: "If I skip a question:" · "Count as 0" · "Exclude from score"
- Pipeline: "Designing your quiz blueprint…" · "Still designing your quiz
  blueprint…" · "Sequencing your questions…" · "Auditing your quiz…" ·
  "Back to Chat" · "Cancel" · "Continue →" · "Retry →" · "Cancelled."
- Quiz: "Your answer" · "Submit Answer" · "Skip →" · "■ End & Get Report" ·
  "Feedback" · "Next Question →" · "✓ Correct" · "✗ Incorrect" ·
  "Please select an option, or use Skip." · "Please write an answer, or use
  Skip." · "No answer options were available for this question." ·
  "🧪 SIMULATION REQUIRED" · "▶ Launch Simulation"
- Report: "MCQ: {c}/{t}" · "Written: {p}%" · skip-mode note · "Start New Quiz"
  · "Review This Quiz →"
- History: "No completed quizzes yet." · "QUESTIONS" · "YOUR ANSWER" ·
  "STANDARD ANSWER" · "SCORE" · "AI FEEDBACK" · "← All Quizzes"
- Tutor: "Select a question on the left to start tutoring."
- Flashcards: "FROM YOUR QUIZZES" · "FROM YOUR LIBRARY" · "Click the card to
  flip it" · "↻ Still learning" · "✓ Got it" · "Deck complete!"
- Settings: section titles + helper copy as in §3.11.

### Required new copy (draft, designer may polish)
- Dashboard hero: "Good evening, Favour" / "N quizzes · M questions · P%
  average"
- Dashboard sections: "Your subjects" · "Needs attention" · "Recent activity"
- Dashboard empty: "Finish your first quiz to see your progress."
- Stepper labels (plain English): "Planning" · "Finding questions" ·
  "Ordering" · "Final checks"

### Empty / error / loading coverage checklist
Every screen needs: empty, loading, error. The report lists a table per screen
in §3; use it as the QA checklist.

---

## 7. UI data model (backend contract)

The renderer talks to the Python sidecar over local HTTP. These are the shapes
it must render. Full questions stay in memory; only small manifests/logs are
persisted (Issue #8 pattern).

```jsonc
// GET /api/dashboard
{
  "quizzes": 7, "questions": 64, "avg_pct": 71,
  "subjects": [ { "name": "Maths", "pct": 88 } ],
  "weak_topics": [ { "topic": "Newton's Laws", "pct": 42,
                     "quiz_ids": ["20260712_143022"] } ],
  "recent": [ { "quiz_id": "...", "created_at": "2025-07-12T14:30:22",
                "topics": ["Physics: Newton's Laws"], "completed": true,
                "mcq": [3,4], "written_pct": 62, "skipped": 1 } ],
  "setup_needed": false
}

// GET /api/flashcards/decks
{ "quiz_decks":  [ { "id": "q:Physics", "title": "Physics", "subject": "Physics",
                     "source": "quiz", "size": 7 } ],
  "library_decks": [ { "id": "lib:chem-L1.1", "title": "L1.1 ...", "subject": "chem",
                     "source": "library", "size": 30 } ] }
// GET /api/flashcards/deck/{id}  → { "cards": [ { "front": "...", "back": "...",
//                                                 "topic": "...", "q_type": "MCQ" } ] }

// Question card (drives the quiz + feedback + review + tutor)
{ "number": 1, "section": "A", "q_type": "MCQ" | "Theory" | "Hybrid",
  "is_simulation": false, "question_text": "...", "options": ["A. ...", "…"],
  "correct_answer": "B. ...", "sim_instruction": "", "sim_name": "",
  "pacing_stage": "Warm-up / Confidence Anchor",
  "objective_type": "conceptual_gap",
  "user_answer": "…", "is_correct": true|null, "score": 0.83|null,
  "ai_feedback": "…", "skipped": false }

// Quiz log list & detail (History/Tutor) — from ~/.quiz_app/logs/*.json
{ "quiz_id": "...", "created_at": "...", "topics": ["..."],
  "completed": true, "summary_report": "...",
  "questions": [ /* question cards as above */ ] }

// Audit result (config-stored; may power a "final checks passed" moment)
{ "audit_status": "PASSED", "checks": { "structural": [...], "diagnostic": {...},
  "preference": {...} }, "missing_items_note": null }
```

---

## 8. Visual direction — fresh redesign

Full liberty. This section is guidance, not prescription.

- **Palette:** current baseline is dark-navy sidebar + light content with
  blue/amber/green/red accents. A fresh system could go either direction; a
  light-and-dark theme pair is recommended. Keep semantic tokens (see below)
  so statuses stay consistent.
- **Semantic color tokens (designer to define values):** `bg-surface`,
  `bg-raised`, `bg-sidebar`, `text-primary`, `text-secondary`, `border`,
  `accent-primary`, `accent-strong`, `success`, `danger`, `warning`,
  `info`, `flashcard`.
- **Type:** a confident UI sans (Inter / system-ui family). Scale: display /
  h1 / h2 / h3 / body / label / mono. Question text must stay ≥12px with good
  line-height; written answers use a mono or comfortable body face.
- **Motion:** 150–250ms ease transitions for nav/flip; progress stepper animates
  subtly; **respect `prefers-reduced-motion`**.
- **A11y:** contrast ≥ WCAG AA on all text; full keyboard navigation; visible
  focus rings; all clickable "cards" are real buttons/links in the DOM.
- **Math rendering:** a LaTeX renderer is NOT required; provide a graceful
  plain-text fallback for `$…$` snippets (monospace, smaller).
- **Iconography:** consistent stroke style; emoji acceptable for playful marks
  (sim, skip) but system icons preferred for UI.

---

## 9. Handoff contract & acceptance checklist

**What the designer returns (any format — Figma, HTML/CSS prototype, or both):**
1. Token set (colors, type, spacing, radii, shadows) — ideally a JSON/CSS
   custom-property file I can import directly.
2. Screen designs or hi-fi prototype for every screen in §3, including the
   empty/loading/error variants.
3. A state-flow diagram covering §5.
4. Component specs (states, sizes) for §4.
5. Final copy (or mark copy as open).
6. Any new IA additions (e.g. richer dashboard) as wireframes.

**Implementation acceptance checklist (I will verify each):**
- [ ] All §3 screens present, functional, matching the approved design.
- [ ] All §5 state combinations render correctly (incl. peek/cancel/retry).
- [ ] §7 contract consumed correctly; no orphaned UI state.
- [ ] Resizes 1040×680 → 760×520 without breakage.
- [ ] Keyboard navigable; focus visible; reduced-motion respected.
- [ ] Empty/error/loading states exist on every screen.
- [ ] LaTeX fallback renders without raw `$` noise.
- [ ] Backend logic unchanged in behaviour; sidecar is a thin adapter.
- [ ] MathType slot is swappable (answer region is an isolated component).

---

## 10. Implementation roadmap

- **Phase A — Skeleton:** Electron + React + TypeScript shell; FastAPI sidecar
  spawning/wrapping `main_app`; one screen wired end-to-end (Dashboard with real
  data) as proof.
- **Phase B — Screens:** implement all §3 screens + §5 state machine to the
  approved design (mock data where pipeline calls aren't wired yet).
- **Phase C — Real wiring:** chat + 6-stage pipeline progress, quiz lifecycle,
  evaluation, review, tutor, flashcards, settings against the sidecar.
- **Phase D — Parity & polish:** keyboard, resize, packaging (Windows/macOS/
  Linux), Puter.js slot, MathType slot, optional embedded sims.

---

## Appendix — data sources used for this handoff

- `main_app/ui/` — main_window.py, quiz_page.py, chat_view.py, review_page.py,
  evaluation_thread.py, flashcards_page.py, theme.py
- `main_app/quiz_logger.py`, `session_log.py` — persistence & stats
- `main_app/flashcard_builder.py` — deck sources (new)
- `main_app/answer_matcher.py`, `library_scanner.py`, `file_retriever.py`,
  `question_generator.py`, `sequencer.py`, `compliance_auditor.py`,
  `agent_runner.py` — pipeline & data shapes
- `AGENT2_WIRING_ISSUES_LOG.md` — roadmap items #1 (Electron), #4 (MathType)
- `X/` — learning-library sample topics and bank formats
