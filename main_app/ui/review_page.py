"""
review_page.py

Read-only quiz review mode. The student picks a completed quiz from the
persistent log files (quiz_logger.py) and browses every question with
their answer and the correct answer both visible. Nothing is editable —
this is a review, not a retake.
"""

import tkinter as tk

from .theme import C, FONT_BODY, FONT_LABEL, FONT_H2, FONT_H3, Page
from .. import quiz_logger


class ReviewPage(Page):

    def __init__(self, parent):
        super().__init__(parent)
        self._log = None   # quiz_logger.QuizLog currently open
        self._idx = 0
        self._build_shell()

    # ── Shell ─────────────────────────────────────────────────────────────────
    def _build_shell(self):
        header = tk.Frame(self, bg=C["content_bg"])
        header.pack(fill="x", padx=36, pady=(30, 0))

        self._title_lbl = tk.Label(header, text="Review", font=FONT_H2,
                                    bg=C["content_bg"], fg=C["text_primary"])
        self._title_lbl.pack(side="left")

        self._back_btn = tk.Label(header, text="← All Quizzes", font=("Segoe UI", 9, "bold"),
                                   bg=C["text_secondary"], fg="white", padx=12, pady=5, cursor="hand2")
        self._back_btn.bind("<Button-1>", lambda _: self._render_quiz_list())

        tk.Frame(self, bg=C["border"], height=1).pack(fill="x", padx=36, pady=16)

        self._body = tk.Frame(self, bg=C["content_bg"])
        self._body.pack(fill="both", expand=True, padx=36, pady=(0, 30))

    def on_show(self):
        self._render_quiz_list()

    def _clear_body(self):
        for w in self._body.winfo_children():
            w.destroy()
        self._back_btn.pack_forget()

    # ── Quiz list ─────────────────────────────────────────────────────────────
    def _render_quiz_list(self):
        self._log = None
        self._clear_body()
        self._title_lbl.config(text="Review")

        quizzes = quiz_logger.list_quiz_logs()
        if not quizzes:
            tk.Label(self._body, text="No completed quizzes yet.", font=FONT_H3,
                     bg=C["content_bg"], fg=C["text_secondary"]).pack(anchor="w", pady=(30, 0))
            return

        canvas = tk.Canvas(self._body, bg=C["content_bg"], highlightthickness=0)
        vscroll = tk.Scrollbar(self._body, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vscroll.set)
        vscroll.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        list_frame = tk.Frame(canvas, bg=C["content_bg"])
        canvas.create_window((0, 0), window=list_frame, anchor="nw")
        list_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        for quiz in quizzes:
            self._make_quiz_row(list_frame, quiz)

    def _make_quiz_row(self, parent, quiz: dict):
        row = tk.Frame(parent, bg=C["card_bg"], highlightbackground=C["border"],
                        highlightthickness=1, cursor="hand2")
        row.pack(fill="x", pady=6)

        inner = tk.Frame(row, bg=C["card_bg"])
        inner.pack(fill="x", padx=16, pady=12)

        topics_text = ", ".join(quiz["topics"]) if quiz["topics"] else "Untitled quiz"
        tk.Label(inner, text=topics_text, font=("Segoe UI", 11, "bold"),
                 bg=C["card_bg"], fg=C["text_primary"]).pack(anchor="w")

        status = "Completed" if quiz["completed"] else "Incomplete"
        status_color = C["correct"] if quiz["completed"] else C["text_secondary"]
        tk.Label(inner, text=f"{quiz['created_at'][:16].replace('T', ' ')}  •  {status}",
                 font=FONT_LABEL, bg=C["card_bg"], fg=status_color).pack(anchor="w", pady=(2, 0))

        for w in (row, inner):
            w.bind("<Button-1>", lambda _, qid=quiz["quiz_id"]: self._open_quiz(qid))

    # ── Quiz detail ───────────────────────────────────────────────────────────
    def _open_quiz(self, quiz_id: str):
        log = quiz_logger.load_quiz_log(quiz_id)
        if not log or not log.questions:
            return
        self._log = log
        self._idx = 0
        self._title_lbl.config(text=", ".join(log.topics) or "Quiz Review")
        self._back_btn.pack(side="right")
        self._render_question()

    def _clear_body_keep_back(self):
        for w in self._body.winfo_children():
            w.destroy()

    def _render_question(self):
        self._clear_body_keep_back()
        record = self._log.questions[self._idx]

        pane = tk.PanedWindow(self._body, orient="horizontal", bg=C["content_bg"],
                               sashwidth=2, sashrelief="flat")
        pane.pack(fill="both", expand=True)

        left = tk.Frame(pane, bg=C["content_bg"])
        pane.add(left, minsize=200)
        right = tk.Frame(pane, bg=C["content_bg"])
        pane.add(right, minsize=340)

        self._render_question_nav(left)
        self._render_question_detail(right, record)

    def _render_question_nav(self, parent):
        tk.Label(parent, text="QUESTIONS", font=("Segoe UI", 8, "bold"),
                 bg=C["content_bg"], fg=C["text_secondary"]).pack(anchor="w", pady=(0, 8))

        canvas = tk.Canvas(parent, bg=C["content_bg"], highlightthickness=0)
        vscroll = tk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vscroll.set)
        vscroll.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        list_frame = tk.Frame(canvas, bg=C["content_bg"])
        canvas.create_window((0, 0), window=list_frame, anchor="nw")
        list_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        for i, record in enumerate(self._log.questions):
            is_active = i == self._idx

            if record.skipped:
                mark, color = "⊘", C["text_secondary"]
            elif record.q_type == 'MCQ':
                ok = record.is_correct
                mark = "✓" if ok else ("✗" if ok is not None else "•")
                color = C["correct"] if ok else (C["incorrect"] if ok is not None else C["text_secondary"])
            else:
                sc = record.score
                mark = f"{sc:.1f}" if sc is not None else "•"
                color = C["correct"] if (sc or 0) >= 0.5 else (C["incorrect"] if sc is not None else C["text_secondary"])

            row = tk.Label(
                list_frame, text=f"{mark}  Q{record.number}", font=FONT_BODY,
                bg=C["active_bg"] if is_active else C["content_bg"],
                fg="white" if is_active else color,
                anchor="w", padx=10, pady=6, cursor="hand2",
            )
            row.pack(fill="x")
            row.bind("<Button-1>", lambda _, i=i: self._jump_to(i))

    def _jump_to(self, idx: int):
        self._idx = idx
        self._render_question()

    def _render_question_detail(self, parent, record):
        tk.Label(parent, text=f"Question {record.number}  •  {record.topic}",
                 font=("Segoe UI", 9, "bold"), bg=C["content_bg"],
                 fg=C["text_secondary"]).pack(anchor="w", pady=(0, 8))

        if record.sim_instruction:
            tk.Label(parent, text=f"🧪 {record.sim_instruction}", font=FONT_LABEL,
                     bg=C["card_bg"], fg=C["text_secondary"], wraplength=420,
                     justify="left", padx=12, pady=8).pack(fill="x", pady=(0, 8))

        q_frame = tk.Frame(parent, bg=C["card_bg"], highlightbackground=C["border"], highlightthickness=1)
        q_frame.pack(fill="x")
        tk.Label(q_frame, text=record.question, font=("Segoe UI", 12), bg=C["card_bg"],
                 fg=C["text_primary"], wraplength=400, justify="left",
                 padx=16, pady=14).pack(fill="x")

        tk.Frame(parent, bg=C["content_bg"], height=14).pack()

        if record.skipped:
            tk.Label(parent, text="⊘ Skipped — not attempted", font=("Segoe UI", 10, "bold"),
                     bg=C["content_bg"], fg=C["text_secondary"]).pack(anchor="w", pady=(0, 10))

        if record.q_type == 'MCQ':
            self._render_mcq_review(parent, record)
        else:
            self._render_subj_review(parent, record)

    def _render_mcq_review(self, parent, record):
        for opt in record.options:
            letter = opt.strip()[:1].upper()
            is_user = letter == (record.user_answer or '').strip().upper()
            correct_letter = (record.correct_answer or '').strip().upper()[:1]
            is_correct_opt = letter == correct_letter

            bg, fg, suffix = C["content_bg"], C["text_primary"], ""
            if is_correct_opt:
                bg, fg, suffix = C["correct"], "white", "  ✓ correct"
            if is_user and not is_correct_opt:
                bg, fg, suffix = C["incorrect"], "white", "  ← your answer"
            elif is_user and is_correct_opt:
                suffix = "  ← your answer, correct"

            tk.Label(parent, text=f"{opt}{suffix}", font=FONT_BODY, bg=bg, fg=fg,
                     anchor="w", padx=12, pady=8).pack(fill="x", pady=2)

    def _render_subj_review(self, parent, record):
        tk.Label(parent, text="YOUR ANSWER", font=("Segoe UI", 8, "bold"),
                 bg=C["content_bg"], fg=C["text_secondary"]).pack(anchor="w", pady=(4, 2))
        tk.Label(parent, text=record.user_answer or "(no answer given)", font=FONT_BODY,
                 bg=C["card_bg"], fg=C["text_primary"], wraplength=400, justify="left",
                 padx=12, pady=8).pack(fill="x")

        tk.Label(parent, text="STANDARD ANSWER", font=("Segoe UI", 8, "bold"),
                 bg=C["content_bg"], fg=C["text_secondary"]).pack(anchor="w", pady=(10, 2))
        tk.Label(parent, text=record.correct_answer or "(not available)", font=FONT_BODY,
                 bg=C["card_bg"], fg=C["text_primary"], wraplength=400, justify="left",
                 padx=12, pady=8).pack(fill="x")

        if record.score is not None:
            tk.Label(parent, text=f"SCORE: {record.score:.2f}", font=("Segoe UI", 9, "bold"),
                     bg=C["content_bg"],
                     fg=C["correct"] if record.score >= 0.5 else C["incorrect"]
                     ).pack(anchor="w", pady=(10, 2))

        if record.ai_feedback:
            tk.Label(parent, text="AI FEEDBACK", font=("Segoe UI", 8, "bold"),
                     bg=C["content_bg"], fg=C["text_secondary"]).pack(anchor="w", pady=(10, 2))
            tk.Label(parent, text=record.ai_feedback, font=FONT_BODY, bg=C["card_bg"],
                     fg=C["text_primary"], wraplength=400, justify="left",
                     padx=12, pady=8).pack(fill="x")
