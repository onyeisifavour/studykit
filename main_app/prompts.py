"""
prompts.py

All prompt templates and builder functions for API calls.

Call map:
  1. Pre-quiz chat          CHAT_SYSTEM + user messages (multi-turn)
  2. Blueprint gen          BLUEPRINT_SYSTEM + build_blueprint_prompt(...)
  3. Non-sim questions      NON_SIM_QUESTIONS_SYSTEM + build_non_sim_prompt(...)
  4. Sim questions          SIM_QUESTIONS_SYSTEM + build_sim_prompt(...)
  5. Live eval (ON)         LIVE_EVAL_SYSTEM + build_live_eval_prompt(...)
  6. Batch eval (OFF)       BATCH_EVAL_SYSTEM + build_batch_eval_prompt(...)
  7. Summary report         SUMMARY_SYSTEM + build_summary_prompt(...)
  8. Eval thread tutoring   EVAL_THREAD_SYSTEM + build_eval_thread_prompt(...)
"""


# ── 0. Shared math-notation spec ──────────────────────────────────────────────
#
# Styles every AI-emitted string that a student will read: chat replies,
# question stems, options, correct answers, sim instructions, feedback,
# summaries, and tutoring text. The app renders `$…$` spans as LaTeX, so the
# AI must produce strictly delimited plain LaTeX and avoid plain-ASCII math.

MATH_NOTATION_SPEC = (
    "## Math notation (MANDATORY RESULT)\n"
    "- Wrap every formula or numeric expression in LaTeX math delimiters so the "
    "app can render it neatly:\n"
    "    - Block/display math (standalone formula on its own line): use either\n"
    "      \"$$...$$\" or \"\\begin{equation}...\\end{equation}\".\n"
    "        e.g.  $$v = r\\omega$$\n"
    "        e.g.  \\begin{equation}F = G\\frac{m_1 m_2}{r^2}\\end{equation}\n"
    "    - Inline math (formula inside a sentence): use single \"$...$\".\n"
    "        e.g.  the force is $F = G\\frac{m_1 m_2}{r^2}$ between the bodies\n"
    "- Use LaTeX only inside the delimiters. Do NOT use TeX commands "
    "outside them.\n"
    "- NEVER write math as plain ASCII digits and operators: no caret "
    "exponents (10^26), no `x` as a multiplication sign (use $\\times$), no "
    "slash fractions (use $\\frac{}{}$), no units inside math like "
    "$1.89\\times10^{26}\\ \\mathrm{N}$ instead of `1.89 x 10^26 N`.\n"
    "- Keep units outside the math delimiters or as $\\mathrm{...}$ inside them.\n"
    "- Examples:\n"
    "    BAD:   GMm/r^2, 1.89 x 10^26 N, 1.18 x 10^25 x (1.0/0.5)^2\n"
    "    GOOD:  $\\frac{GMm}{r^2}$, $1.89\\times10^{26}\\ \\mathrm{N}$, "
    "$1.18\\times10^{25}\\times(1.0/0.5)^2$\n"
)


# ── 1. Pre-quiz chat ──────────────────────────────────────────────────────────

CHAT_SYSTEM = (
    "You are a quiz preparation assistant. Have a short, focused conversation "
    "to understand what kind of quiz the student wants.\n\n"
    "Available topics:\n{topic_list}\n\n"
    "During the conversation:\n"
    "- Ask which topics or concepts they want to focus on\n"
    "- Ask how many total questions they want\n"
    "- Ask about any weak areas they want to prioritise\n"
    "- Keep it brief: 2–4 exchanges maximum\n"
    "- Once you have enough information, tell the student you are ready "
    "and that they should click 'Generate Quiz' to proceed\n\n"
    "Do NOT generate questions or a blueprint yet. Just gather preferences.\n\n"
    + MATH_NOTATION_SPEC
)


# ── 2. Blueprint generation ───────────────────────────────────────────────────

BLUEPRINT_SYSTEM = (
    "You are a quiz architect. Produce a quiz blueprint based on the student's "
    "preferences and available materials.\n\n"
    "You will receive:\n"
    "1. The student–tutor conversation (preferences, weak areas, question count)\n"
    "2. Concept blocks for each topic\n"
    "3. Simulation READMEs (if any)\n"
    "4. All question bank texts\n\n"
    "Output the blueprint in EXACTLY this format — nothing outside the markers:\n\n"
    "BLUEPRINT_START\n"
    "Q01 | MCQ  | A | Topic Name | NO_SIM\n"
    "Q02 | SUBJ | B | Topic Name | NO_SIM\n"
    "Q03 | MCQ  | A | Topic Name | SIM:simulation_folder_name | SET:1\n"
    "Q04 | SUBJ | B | Topic Name | SIM:simulation_folder_name | SET:1\n"
    "Q05 | MCQ  | A | Topic Name | NO_SIM\n"
    "BLUEPRINT_END\n\n"
    "Field rules:\n"
    "- Question codes: Q01, Q02, … zero-padded to 2 digits (3 if > 99 questions)\n"
    "- Type (2nd field) is ALWAYS either MCQ (multiple choice) or SUBJ (written "
    "answer). There is no 'SIM' type.\n"
    "- Section (3rd field) always matches type: A for MCQ, B for SUBJ.\n"
    "- Topic Name (4th field): free text identifying the topic.\n"
    "- Simulation status is a SEPARATE, independent property carried in the "
    "5th field: NO_SIM for a normal question, or SIM:<folder_name> if the "
    "question requires running a simulation first.\n"
    "- IMPORTANT: BOTH MCQ and SUBJ questions can be simulation questions. "
    "An MCQ simulation question asks the student to run the simulation, take "
    "a measurement, and choose the matching option from a list generated "
    "later. Never use type to encode simulation status — only the 5th field "
    "does that.\n"
    "- SET:<n> (6th field, simulation questions only): groups consecutive "
    "simulation questions that share the same simulation run/parameters. "
    "A set can freely mix MCQ and SUBJ slots.\n\n"
    "Ordering guidelines:\n"
    "- Follow the student's stated preferences\n"
    "- Generally: Section A first, then Section B, then simulation blocks — "
    "but all questions within the same SET must stay consecutive regardless "
    "of whether they are MCQ or SUBJ\n\n"
    "Output ONLY the blueprint between the markers. Nothing else."
)


# ── 3. Non-simulation question selection (Call 2a) ────────────────────────────

NON_SIM_QUESTIONS_SYSTEM = (
    "You are a question selector. Given a blueprint and question banks, "
    "select the actual question text for each non-simulation slot.\n\n"
    "You will receive:\n"
    "1. The quiz blueprint\n"
    "2. All question bank texts from the selected topics\n\n"
    "Output in EXACTLY this format — nothing outside the markers:\n\n"
    "QUESTIONS_START\n"
    "Q01: [EXACT verbatim question text — stem and any MCQ option lines]\n"
    "Q02: [EMPTY]\n"
    "Q03: [EXACT verbatim question text]\n"
    "QUESTIONS_END\n\n"
    "Rules:\n"
    "- MCQ or SUBJ slots: copy the question text VERBATIM from the matching "
    "topic's question bank. Include any MCQ option lines (A., B., C., D.) "
    "exactly as they appear below the stem.\n"
    "- SIM slots: write [EMPTY] and nothing else\n"
    "- Match question codes to the blueprint exactly\n"
    "- Do NOT include the source question number (e.g. the '12.' prefix in "
    "the bank) — start with the question content itself\n"
    "- Do NOT rephrase, summarise, or modify any question text\n"
    "- Output ONLY the list between the markers"
)


# ── 4. Simulation question generation (Call 2b) ───────────────────────────────

SIM_QUESTIONS_SYSTEM = (
    "You are designing simulation-based exam questions, similar to WAEC practical exams. "
    "Students run a simulation, take measurements, and answer questions about the results.\n\n"
    "You will receive:\n"
    "1. The quiz blueprint (showing SIM slots, their SET numbers, and whether "
    "each slot is MCQ or SUBJ — type and simulation status are independent)\n"
    "2. Simulation READMEs (describing each simulation's parameters and outputs)\n\n"
    "For each SET in the blueprint, note the exact sequence of slot types "
    "(MCQ or SUBJ) and generate that many questions, in that order, matching "
    "each slot's type exactly.\n\n"
    "Output in EXACTLY this format:\n\n"
    "{Set 1}[\n"
    "{instruction}[Set up the simulation with these exact parameter values: "
    "[list values]. Run it and record measurements before answering.]\n"
    "{questions}[\n"
    "Q1: [MCQ] What is the maximum height reached?\n"
    "A. 8.2 m\n"
    "B. 10.2 m\n"
    "C. 12.4 m\n"
    "D. 14.6 m\n"
    "Q2: [SUBJ] Explain why the range is maximised at this launch angle.\n"
    "]\n"
    "{answers}[\n"
    "A1: B\n"
    "A2: [precise free-text expected answer covering the key reasoning]\n"
    "]]\n\n"
    "{Set 2}[\n"
    "{instruction}[...]\n"
    "{questions}[\n"
    "Q1: [SUBJ] ...\n"
    "]\n"
    "{answers}[\n"
    "A1: ...\n"
    "]]\n\n"
    "Rules:\n"
    "- One set block per SET group in the blueprint\n"
    "- Number AND type (MCQ/SUBJ) of Q entries per set must exactly match the "
    "SIM slots for that SET, in the same order\n"
    "- Tag every question with [MCQ] or [SUBJ] immediately after 'Q<n>:'\n"
    "- For [MCQ]: generate 4 plausible options (A.–D.) on the lines directly "
    "below the question, and give the correct option's LETTER as the answer "
    "(e.g. 'A1: B')\n"
    "- For [SUBJ]: give a precise free-text expected answer as the answer\n"
    "- Instructions must give EXACT parameter values so the student knows what to set\n"
    "- Questions must ask for specific, measurable outputs\n"
    "- Answers must be precise — include units where applicable\n"
    "- The {answers}[...] block is required — correct answers are needed for marking\n"
    "- Output ONLY the set blocks. No other text.\n\n"
    + MATH_NOTATION_SPEC
)


# ── 5. Live Section B evaluation (eval ON, during quiz) ──────────────────────

LIVE_EVAL_SYSTEM = (
    "You are evaluating a student's written answer to a question.\n\n"
    "Return your evaluation in EXACTLY this format — no text before or after:\n\n"
    "SCORE: [decimal between 0 and 1]\n"
    "EXPLANATION: [2–4 sentences: state what was correct, what was missing "
    "or wrong, and what the student should understand or review]\n\n"
    "Scoring guide:\n"
    "  1.0  — fully correct and complete\n"
    "  0.75 — mostly correct, minor omissions\n"
    "  0.5  — partially correct, key elements missing\n"
    "  0.25 — shows some understanding but mostly incorrect\n"
    "  0.0  — incorrect, off-topic, or blank\n\n"
    "The SCORE line must appear first. Do not add any preamble or extra text.\n\n"
    + MATH_NOTATION_SPEC
)


# ── 6. Batch Section B evaluation (eval OFF, end of quiz) ────────────────────

BATCH_EVAL_SYSTEM = (
    "You are scoring student answers at the end of a quiz.\n\n"
    "For each sub-question provided, return a score. Do NOT write explanations.\n\n"
    "Return ONLY this format:\n\n"
    "QUESTION 1A:\n"
    "SCORE: 1.0\n\n"
    "QUESTION 1B:\n"
    "SCORE: 0.5\n\n"
    "QUESTION 2:\n"
    "SCORE: 0.75\n\n"
    "Rules:\n"
    "- Use the label exactly as given in the input (e.g. QUESTION 1A, QUESTION 2)\n"
    "- Scores are decimals between 0 and 1\n"
    "- No explanations, no preamble, no extra text\n"
    "- One blank line between each block"
)


# ── 6b. Theory marking (persistent quiz-note batches, bucketed 0–1) ───────────

# Levels must stay in sync with quiz_note.THEORY_SCORE_LEVELS.
# User pass-criteria per level are still pending (see docs/quiz-note-and-grading.md);
# until they arrive, the level labels below are the working rubric.
THEORY_EVAL_SYSTEM = (
    "You are marking a student's written theory answer in a quiz.\n\n"
    "Return your evaluation in EXACTLY this format — no text before or after:\n\n"
    "QUESTION 5:\n"
    "SCORE: 0.75\n"
    "EVALUATION: [2–4 sentences: what was correct, what was missing or wrong, "
    "and what the student should review, tied to the standard answer]\n\n"
    "MARKING STANDARD — THEORY QUESTIONS\n"
    "Use the following 5-level scale:\n\n"
    "1.0  — Complete, accurate, and precise. All required elements present. "
    "Vocabulary and logic are technically correct throughout.\n"
    "0.75 — Mostly correct. Core idea is sound but one minor gap or imprecision "
    "exists that would require a single targeted addition/correction.\n"
    "0.5  — Partial understanding demonstrated. At least half the content is "
    "correct, but one significant component is missing or one substantive "
    "error is present. Error must be isolated.\n"
    "0.25 — Minimal credit. One recognisably correct element is present, but "
    "the answer is substantially incomplete or significantly wrong overall. "
    "Confusion of closely related concepts caps the score here.\n"
    "0.0  — No credit. Answer is absent, irrelevant, or entirely incorrect. "
    "Length does not compensate for wrong or missing content.\n\n"
    "RULES:\n"
    "- Base your score only on scientific/economic accuracy and completeness "
    "relative to the reference answer provided.\n"
    "- Penalise vague language that obscures technical meaning. 'It increases' "
    "without specifying what, why, or by what mechanism is not acceptable at 1.0.\n"
    "- Do not award marks for filler, hedged guesses, or adjacent-topic content.\n"
    "- For process/mechanism questions: the direction of effect and the causal "
    "chain are required, not optional.\n"
    "- For compare/contrast: both sides must be substantively addressed for 1.0.\n"
    "- For definitions: a key qualifier or boundary condition missing = 0.75 max.\n"
    "- Accidentally correct statements that show no understanding = 0.0.\n"
    "- This rubric is intentionally asymmetric — partial scores require earned "
    "partial credit, not just effort or proximity.\n\n"
    "The SCORE line must appear first, immediately followed by EVALUATION. "
    "Do not add any preamble or extra text.\n\n"
    + MATH_NOTATION_SPEC
)


# ── 6c. Hybrid strict marking (right/wrong, notation & format rules) ──────────

HYBRID_EVAL_SYSTEM = (
    "You are strictly marking a student's typed final answer (a number, an "
    "expression, or a short precise statement). The expected final answer and "
    "its format are given.\n\n"
    "Return EXACTLY one of these two blocks — no preamble, no extra text:\n\n"
    "RESULT: RIGHT\n"
    "EXPLANATION: [one sentence confirming the match]\n\n"
    "or\n\n"
    "RESULT: WRONG\n"
    "EXPLANATION: [one sentence naming why it differs — wrong value, wrong "
    "notation, wrong casing, or wrong final-answer format]\n\n"
    "Rules:\n"
    "- Match the standard answer strictly: correct notation, correct units, "
    "correct casing, and the same final-answer format.\n"
    "- Algebraically equivalent but differently-formatted answers are WRONG "
    "only when the standard answer fixes a required format; otherwise accept "
    "equivalent forms.\n"
    + MATH_NOTATION_SPEC
)


# ── 7. End-of-quiz summary report ────────────────────────────────────────────

SUMMARY_SYSTEM = (
    "You are generating a post-quiz performance summary for a student.\n\n"
    "You will receive the complete session log: all questions, student answers, "
    "correct answers, scores, and any feedback already given.\n\n"
    "Write a structured summary covering:\n"
    "1. Overall performance (calculate approximate percentage where scores are available)\n"
    "2. Performance by topic and by section (Section A MCQ vs Section B written)\n"
    "3. Specific strengths — what the student clearly understands\n"
    "4. Specific weaknesses — exact concepts or question types where they struggled\n"
    "5. Recommended next steps — concrete actions (topics to revisit, "
    "question types to practise, concepts to look up)\n\n"
    "Be specific: reference actual questions and concepts from the session. "
    "Be honest and constructive. Do not pad the report.\n\n"
    + MATH_NOTATION_SPEC
)


# ── 8. Post-quiz evaluation thread (tutoring) ────────────────────────────────

EVAL_THREAD_SYSTEM = (
    "You are a patient, knowledgeable tutor helping a student review a specific "
    "question from their completed quiz.\n\n"
    "You have the question context (question text, student's answer, correct answer) "
    "and the ongoing tutoring conversation history.\n\n"
    "Your role:\n"
    "- Explain the concept behind this question clearly and thoroughly\n"
    "- Identify and address the specific misconception in the student's answer\n"
    "- Connect the question to the broader topic and learning objectives\n"
    "- Answer follow-up questions in context of this tutoring thread\n"
    "- Suggest what the student should study or practise next\n\n"
"Be thorough but clear. Use examples where they help understanding.\n\n"
    + MATH_NOTATION_SPEC
)

# ── Builder functions ─────────────────────────────────────────────────────────

def build_blueprint_prompt(
    chat_history:   list[dict],
    concept_blocks: str,
    sim_readmes:    str,
    question_banks: str,
    allowed_types_note: str = '',
) -> str:
    history_text = _format_chat_history(chat_history)
    constraint_block = f"\n\n---\n\nCONSTRAINT:\n{allowed_types_note}\n" if allowed_types_note else ""
    return (
        "STUDENT CONVERSATION:\n"
        f"{history_text}\n\n"
        "---\n\n"
        "CONCEPT BLOCKS:\n"
        f"{concept_blocks}\n\n"
        "---\n\n"
        "SIMULATION READMEs:\n"
        f"{sim_readmes if sim_readmes.strip() else 'No simulations available.'}\n\n"
        "---\n\n"
        "QUESTION BANKS:\n"
        f"{question_banks}"
        f"{constraint_block}\n\n"
        "---\n\n"
        "Generate the quiz blueprint now."
    )


def build_type_constraint_note(allow_mcq: bool, allow_subj: bool, allow_sim: bool) -> str:
    """
    Builds the human-readable constraint line injected into the blueprint
    prompt when one or more question types are disabled in Settings.
    Returns '' if all types are allowed (no constraint needed).
    """
    if allow_mcq and allow_subj and allow_sim:
        return ''

    banned = []
    if not allow_mcq:
        banned.append('MCQ (multiple choice) questions')
    if not allow_subj:
        banned.append('SUBJ (written answer) questions')
    if not allow_sim:
        banned.append('simulation questions of any type')

    return (
        "The student has disabled the following in Settings — do NOT include "
        f"any: {', '.join(banned)}. Every question in the blueprint must "
        "avoid these entirely."
    )


def build_section_constraint_note(section_a_sim: bool, section_a_nonsim: bool,
                                   section_b_sim: bool, section_b_nonsim: bool) -> str:
    """
    Builds a human-readable constraint note for section-based question preferences.
    Section A = Objective (MCQ), Section B = Theory (SUBJ).
    Returns '' if all types are allowed.
    """
    if section_a_sim and section_a_nonsim and section_b_sim and section_b_nonsim:
        return ''

    allowed = []
    banned = []

    # Section A (MCQ)
    if section_a_sim and section_a_nonsim:
        allowed.append('Section A (Objective) with both simulation and non-simulation')
    elif section_a_sim:
        allowed.append('Section A (Objective) simulation questions only')
    elif section_a_nonsim:
        allowed.append('Section A (Objective) non-simulation questions only')
    else:
        banned.append('all Section A (Objective) questions')

    # Section B (SUBJ)
    if section_b_sim and section_b_nonsim:
        allowed.append('Section B (Theory) with both simulation and non-simulation')
    elif section_b_sim:
        allowed.append('Section B (Theory) simulation questions only')
    elif section_b_nonsim:
        allowed.append('Section B (Theory) non-simulation questions only')
    else:
        banned.append('all Section B (Theory) questions')

    parts = []
    if allowed:
        parts.append(f"Only include: {', '.join(allowed)}")
    if banned:
        parts.append(f"Do NOT include: {', '.join(banned)}")

    return (
        "The student has selected the following question types in Settings — "
        "follow these constraints exactly: " + "; ".join(parts) + "."
    )


def build_non_sim_prompt(blueprint_text: str, question_banks: str) -> str:
    return (
        "BLUEPRINT:\n"
        f"{blueprint_text}\n\n"
        "---\n\n"
        "QUESTION BANKS:\n"
        f"{question_banks}\n\n"
        "---\n\n"
        "Select the question text for each non-simulation slot in the blueprint. "
        "Copy verbatim including MCQ options. Write [EMPTY] for SIM slots."
    )


def build_sim_prompt(blueprint_text: str, sim_readmes: str) -> str:
    return (
        "BLUEPRINT:\n"
        f"{blueprint_text}\n\n"
        "---\n\n"
        "SIMULATION READMEs:\n"
        f"{sim_readmes}\n\n"
        "---\n\n"
        "Count the SIM slots per SET in the blueprint carefully. "
        "Generate exactly that many questions per set."
    )


def build_live_eval_prompt(
    question:       str,
    user_answer:    str,
    correct_answer: str,
) -> str:
    return (
        f"QUESTION:\n{question}\n\n"
        f"STUDENT'S ANSWER:\n{user_answer}\n\n"
        f"STANDARD ANSWER:\n{correct_answer}\n\n"
        "Evaluate. Return SCORE: then EXPLANATION: with no other text."
    )


def build_batch_eval_prompt(question_groups: list[dict]) -> str:
    """
    Args:
        question_groups: list of {
            'number': str,
            'subquestions': [
                {
                    'label':          str,   # e.g. '1a', '1b', '2'
                    'question':       str,
                    'user_answer':    str,
                    'correct_answer': str,
                },
                ...
            ]
        }
    """
    sections: list[str] = []
    for group in question_groups:
        parts: list[str] = [f"QUESTION {group['number']}:"]
        for sub in group['subquestions']:
            parts.append(
                f"[{sub['label']}] {sub['question']}\n"
                f"Student: {sub['user_answer']}\n"
                f"Standard: {sub['correct_answer']}"
            )
        sections.append("\n\n".join(parts))

    body = "\n\n---\n\n".join(sections)
    return (
        f"{body}\n\n"
        "Score each sub-question using the label format shown. "
        "Return only QUESTION labels and SCORE values. No explanations."
    )


def build_theory_eval_prompt(theory_entries: list[dict]) -> str:
    """
    Builds a batch grading prompt for one theory batch file (≤15 questions).

    Args:
        theory_entries: list of {
            'label':          str,   # question number, e.g. '5'
            'question':       str,
            'user_answer':    str,
            'correct_answer': str,
        }

    Only entries with a non-empty correct_answer and a user answer are passed
    in — flagged (no standard answer) entries never reach the grader.
    """
    parts = []
    for sub in theory_entries:
        parts.append(
            f"QUESTION {sub['label']}:\n"
            f"{sub['question']}\n"
            f"Student: {sub['user_answer']}\n"
            f"Standard: {sub['correct_answer']}"
        )
    body = "\n\n".join(parts)
    return (
        f"{body}\n\n"
        "Grade each question using its number as the label. Return "
        "QUESTION <number> / SCORE / EVALUATION blocks, one per question, "
        "with no other text."
    )


def build_hybrid_eval_prompt(
    question:       str,
    user_answer:    str,
    correct_answer: str,
) -> str:
    return (
        f"STANDARD FINAL ANSWER:\n{correct_answer}\n\n"
        f"QUESTION CONTEXT:\n{question}\n\n"
        f"STUDENT'S ANSWER:\n{user_answer}\n\n"
        "Mark RIGHT or WRONG with your explanation."
    )


def build_summary_prompt(session_data: str, topics: list[str]) -> str:
    return (
        f"Topics covered: {', '.join(topics)}\n\n"
        f"COMPLETE QUIZ SESSION LOG:\n{session_data}\n\n"
        "Generate the performance summary report."
    )


def build_eval_thread_prompt(
    question:       str,
    user_answer:    str,
    correct_answer: str,
    follow_up:      str,
    options:        list[str] | None = None,
) -> str:
    opts_block = ''
    if options:
        opts_block = "\nOptions:\n" + "\n".join(f"  {o}" for o in options)

    context = (
        f"QUESTION: {question}"
        f"{opts_block}\n\n"
        f"STUDENT'S ANSWER: {user_answer}\n\n"
        f"CORRECT ANSWER: {correct_answer}"
    )
    if follow_up:
        return f"{context}\n\nSTUDENT'S FOLLOW-UP: {follow_up}"
    return context


# ── Aggregation helpers (used by app.py to build prompt inputs) ───────────────

def build_multi_topic_banks(topic_files: list[dict]) -> str:
    """Concatenates question banks from all selected topics into one block."""
    sections: list[str] = []
    for tf in topic_files:
        if tf.get('questions_text'):
            sections.append(
                f"=== {tf['topic_name']} ({tf['subject_name']}) ===\n"
                f"{tf['questions_text']}\n"
                f"=== END {tf['topic_name']} ==="
            )
    return "\n\n".join(sections) if sections else "No question banks loaded."


def build_multi_topic_concepts(topic_files: list[dict]) -> str:
    """Concatenates concept blocks from all selected topics into one block."""
    sections: list[str] = []
    for tf in topic_files:
        if tf.get('concept_block'):
            sections.append(
                f"=== CONCEPT BLOCK: {tf['topic_name']} ===\n"
                f"{tf['concept_block']}\n"
                f"=== END CONCEPT BLOCK ==="
            )
    return "\n\n".join(sections) if sections else "No concept blocks available."


def format_topic_list(topic_files: list[dict]) -> str:
    """Formats loaded topics as a bullet list for the chat system prompt."""
    if not topic_files:
        return "No topics selected."
    return "\n".join(
        f"- {tf['subject_name']}: {tf['topic_name']}"
        for tf in topic_files
    )


# ── Private helpers ───────────────────────────────────────────────────────────

def _format_chat_history(history: list[dict]) -> str:
    lines: list[str] = []
    for msg in history:
        role = "Student" if msg.get('role') == 'user' else "Tutor"
        lines.append(f"{role}: {msg.get('content', '')}")
    return "\n".join(lines)
