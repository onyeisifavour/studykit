# Quiz Note & Grading

How a built quiz is persisted locally and how each question gets marked,
scored, and reported — designed to work with both live ("Evaluation ON") and
deferred ("Evaluation OFF") marking.

## Storage layout

Everything lives under `~/.quiz_app/quizzes/<quiz_id>/`:

| File                | Contents                                                     |
| ------------------- | ------------------------------------------------------------ |
| `quiz.json`         | Master note: metadata + every question with its answers/marks |
| `theory_batch_00.json` … | ≤ 15 Theory questions each — the only file a theory grader sees |

`config['current_quiz_id']` points at the most recently built note.

`quiz_id` is a deterministic `sha1` of the ordered question sequence (12 hex
chars). The note is **reused** when its `content_sig` (a hash of the question
content) matches the last persisted note, so resuming the same quiz keeps the
student's answers and marks. A stale id collision is scoped uniquely via the
signature prefix.

## The note (`quiz.json`)

```jsonc
{
  "quiz_id": "abc123def456",
  "content_sig": "…",
  "created_at": "…",
  "updated_at": "…",
  "topics": ["Gravitational Fields and Orbital Mechanics"],
  "subjects": ["physics"],
  "total_questions": 10,
  "evaluation_on": null,          // set when the quiz is completed
  "skip_mode": null,              // 'zero' | 'exclude'
  "sequence_metadata": { … },     // pacing/cognitive-flow info from the manifest
  "history_written": false,
  "meta": { },
  "questions": [ /* one entry per question (below) */ ]
}
```

Per-question entry:

```jsonc
{
  "index": 0, "number": 1, "section": "A",          // section A = MCQ, B = written
  "type": "MCQ" | "Hybrid" | "Theory",
  "format": "Sim" | "Non-Sim",
  "is_simulation": false,
  "topic": "…", "subject": "…",
  "objective_type": "…", "pacing_stage": "…",
  "position_rationale": "…", "source": "…",
  "question_text": "…",
  "options": ["A. …", "B. …"],
  "sim_name": "", "sim_instruction": "",
  "correct_answer": "…",
  "correct_answer_present": true,   // false ⇒ never sent to a grader
  "user_choice": null,              // filled in when the student answers
  "choice_meta": null,              // {kind:'option', index} for MCQ
  "skipped": false,
  "score": null,                    // filled by the marking pass
  "remark": null,                   // 'right' | 'wrong' | eval note | status
  "eval":   null                    // {source, score, note, triggered_at} once graded
}
```

`correct_answer` is populated **before** the quiz runs for MCQs, Hybrids, bank
theories and pre-declared sim answers. Theory questions with no standard answer
get `correct_answer_present: false`.

## Marking semantics

- **MCQ** — checked locally against the pre-declared answer in the note.
  Correct = `1.0`, remark `right`; otherwise `0.0`, remark `wrong`.
- **Hybrid** — a normalization fast path (NFKC, unified `×·−`, whitespace)
  accepts equivalent answers without any AI call. Non-matching answers go to a
  strict AI rubric (`HYBRID_EVAL_SYSTEM`) that returns RIGHT/WRONG with format,
  notation and casing rules. Correct = `1.0` / `right`, wrong = `0.0` / `wrong`.
- **Theory** — graded in parallel, one thread per batch file (≤ 15 questions
  each), on the **5-level rubric** below. The raw rubric verdict is written
  straight to the note with `score`, `remark` (the evaluation summary) and the
  full `eval` payload; `snap_score` is a defensive pass-through for stray
  values.
- **Flagged theory** (`correct_answer_present: false`) is recorded in the note
  and quiz log but **never sent to a grader** — it shows as ungraded, not as 0.
- **Unanswered** (no choice, not skipped) and **skipped** are not graded.
  Skipped counts as `0.0` under `skip_mode='zero'` or is omitted entirely under
  `'exclude'`.

## Theory rubric (5-level, precision-first)

| Level | Anchor |
| ----- | ------ |
| 1.0   | Complete, accurate, and precise — all required elements, correct vocabulary, no omissions |
| 0.75  | Mostly correct — the core idea is sound with one missing/mis-stated/underspecified element that a single targeted addition would fix |
| 0.5   | Genuine partial understanding — at least half correct, but one significant component missing or one substantive (isolated) error |
| 0.25  | Minimal credit — one recognisably correct element, but substantially incomplete or significantly wrong overall; confusing closely related concepts caps the score here |
| 0.0   | No credit — absent, irrelevant, factually wrong (not a minor slip), filler, or hedged guess; length never compensates |

Grading rules (as prompted in `THEORY_EVAL_SYSTEM`):

- Vague language that obscures technical meaning ("it increases" without
  mechanism) is never 1.0.
- Process questions **require** the causal chain and direction of effect.
- Compare/contrast requires both sides substantively addressed for 1.0.
- A missing key qualifier/boundary condition on a definition caps at **0.75**.
- Accidentally-correct statements with no demonstrated understanding = **0.0**.
- The scale is asymmetric: partial credit must be *earned*, not proximity-based.

Levels must stay in sync between `quiz_note.THEORY_SCORE_LEVELS` and the rubric
text in `THEORY_EVAL_SYSTEM`.

## Evaluation ON vs deferred (OFF)

- **Evaluation ON** — live per-question feedback already exists in the UI; the
  note's `eval` fields are also populated at end-of-quiz by the same complete
  pass, so the note is always a complete record.
- **Evaluation OFF** — nothing is scored during the quiz. At `endQuiz` the
  renderer posts every answer to `POST /api/quiz/complete`, which runs the
  marking pass in the background (parallel theory batches) and updates the note
  and the quiz log. `eval` stays `null` until that pass writes it.

## API

- `POST /api/quiz/complete`
  Body: `{ quiz_id?, answers: [{ number, user_choice, choice_meta, skipped }],
  evaluation_on, skip_mode?, topics? }`
  Runs `quiz_grader.complete_quiz` and returns
  `{ quiz_id, history_written, profile, results }`.
- `GET /api/quiz/note/{quiz_id}` — full note + `score_profile` (overall %,
  earned points, totals by type / pacing stage / topic).
- `GET /api/quiz/last/note` — note + profile for `current_quiz_id`.

`quiz_grader.complete_quiz` also writes a `quiz_logger` entry, so completed
Electron quizzes finally appear on the History screen and dashboard.

## Score profile

`quiz_note.score_profile(note, skip_mode)` produces:

```
{ total, attempted, marked, skipped, unanswered, ungraded,
  earned, overall, by_type, by_pacing_stage, by_topic }
```

- `overall` = `earned / attempted × 100` (attempted = answered + skipped-if-zero).
- By-type buckets include a `correct` count for MCQ/Hybrid (full credit only).

## Verification checklist

1. `python -m py_compile main_app/quiz_note.py main_app/quiz_grader.py …`
2. Offline smoke: `ensure_note` reuse, theory batch split (16 → 2 files at 15),
   `set_user_choice` round-trip, `set_theory_mark` writes both note + batch,
   `snap_score`, `score_profile`.
3. `desktop`: `npm run typecheck` and `npm run build`.
4. Sidecar import: `.venv/bin/python -c "from main_app.sidecar.app import app"`.
5. Live end-to-end: generate/restart a quiz, answer, `endQuiz`, confirm
   `quiz.json` + theory batches appear, verdicts populate, History lists the
   quiz, and the report shows the bucketed scores.