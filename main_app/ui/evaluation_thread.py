"""
evaluation_thread.py

Post-quiz tutoring interface. The student picks a completed quiz, picks a
specific question from it, and starts a focused tutoring conversation with
the AI about that question. Each question keeps its own thread history so
switching between questions preserves separate conversations.
"""

import tkinter as tk

from .theme import C, FONT_BODY, FONT_LABEL, FONT_H2, Page
from .. import quiz_logger


class EvaluationThreadPage(Page):

    def __init__(self, parent, root, evaluation_runner):
        super().__init__(parent)
        self._root   = root
        self._runner = evaluation_runner

        self._log             = None   # currently open QuizLog
        self._current_record  = None   # currently selected QuestionRecord
        self._threads: dict[int, list[dict]] = {}   # question index -> chat history
        self._waiting         = False
        self._list_pane       = None

        self._build_shell()

    # ── Shell ─────────────────────────────────────────────────────────────────
    def _build_shell(self):
        header = tk.Frame(self, bg=C["content_bg"])
        header.pack(fill="x", padx=36, pady=(30, 0))

        self._title_lbl = tk.Label(header, text="Tutor", font=FONT_H2,
                                    bg=C["content_bg"], fg=C["text_primary"])
        self._title_lbl.pack(side="left")

        self._back_btn = tk.Label(header, text="← All Quizzes", font=("Segoe UI", 9, "bold"),
                                   bg=C["text_secondary"], fg="white", padx=12, pady=5, cursor="hand2")
        self._back_btn.bind("<Button-1>", lambda _: self._render_quiz_list())

        tk.Frame(self, bg=C["border"], height=1).pack(fill="x", padx=36, pady=16)

        self._body = tk.Frame(self, bg=C["content_bg"])
        self._body.pack(fill="both", expand=True, padx=36, pady=(0, 30))

    def on_show(self):
        if self._log is None:
            self._render_quiz_list()

    def _clear_body(self):
        for w in self._body.winfo_children():
            w.destroy()

    # ── Quiz list ─────────────────────────────────────────────────────────────
    def _render_quiz_list(self):
        self._log = None
        self._current_record = None
        self._threads.clear()
        self._back_btn.pack_forget()
        self._clear_body()
        self._title_lbl.config(text="Tutor")

        quizzes = quiz_logger.list_quiz_logs()
        if not quizzes:
            tk.Label(self._body, text="No completed quizzes yet. Finish a quiz first.",
                     font=("Segoe UI", 13, "bold"), bg=C["content_bg"],
                     fg=C["text_secondary"]).pack(anchor="w", pady=(30, 0))
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
        tk.Label(inner, text=quiz["created_at"][:16].replace("T", " "), font=FONT_LABEL,
                 bg=C["card_bg"], fg=C["text_secondary"]).pack(anchor="w", pady=(2, 0))

        for w in (row, inner):
            w.bind("<Button-1>", lambda _, qid=quiz["quiz_id"]: self._open_quiz(qid))

    # ── Quiz opened: question picker + chat ───────────────────────────────────
    def _open_quiz(self, quiz_id: str):
        log = quiz_logger.load_quiz_log(quiz_id)
        if not log or not log.questions:
            return
        self._log = log
        self._current_record = None
        self._threads.clear()
        self._title_lbl.config(text=", ".join(log.topics) or "Tutor")
        self._back_btn.pack(side="right")
        self._render_split_view()

    def _render_split_view(self):
        self._clear_body()

        pane = tk.PanedWindow(self._body, orient="horizontal", bg=C["content_bg"],
                               sashwidth=2, sashrelief="flat")
        pane.pack(fill="both", expand=True)

        self._list_pane = tk.Frame(pane, bg=C["content_bg"])
        pane.add(self._list_pane, minsize=260)
        self._chat_container = tk.Frame(pane, bg=C["content_bg"])
        pane.add(self._chat_container, minsize=360)

        self._render_question_list()
        self._render_no_question_selected()

    def _render_question_list(self):
        for w in self._list_pane.winfo_children():
            w.destroy()

        tk.Label(self._list_pane, text="SELECT A QUESTION", font=("Segoe UI", 8, "bold"),
                 bg=C["content_bg"], fg=C["text_secondary"]).pack(anchor="w", pady=(0, 8))

        canvas = tk.Canvas(self._list_pane, bg=C["content_bg"], highlightthickness=0)
        vscroll = tk.Scrollbar(self._list_pane, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vscroll.set)
        vscroll.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        list_frame = tk.Frame(canvas, bg=C["content_bg"])
        canvas.create_window((0, 0), window=list_frame, anchor="nw")
        list_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        for record in self._log.questions:
            is_active = self._current_record is not None and record.index == self._current_record.index
            preview = (record.question[:34] + "…") if len(record.question) > 34 else record.question
            row_bg = C["active_bg"] if is_active else C["content_bg"]
            row_fg = "white" if is_active else C["text_secondary"]

            row = tk.Frame(list_frame, bg=row_bg, cursor="hand2")
            row.pack(fill="x")
            num_lbl = tk.Label(row, text=f"Q{record.number}", font=("Segoe UI", 9, "bold"),
                                bg=row_bg, fg="white" if is_active else C["text_primary"],
                                anchor="w", padx=10, pady=6)
            num_lbl.pack(side="left")
            prev_lbl = tk.Label(row, text=preview, font=FONT_LABEL,
                                 bg=row_bg, fg=row_fg, anchor="w")
            prev_lbl.pack(side="left", fill="x", expand=True)

            for w in (row, num_lbl, prev_lbl):
                w.bind("<Button-1>", lambda _, r=record: self._select_question(r))

    def _select_question(self, record):
        self._current_record = record
        self._threads.setdefault(record.index, [])
        self._render_question_list()
        self._render_chat_panel()

    def _render_no_question_selected(self):
        for w in self._chat_container.winfo_children():
            w.destroy()
        tk.Label(self._chat_container, text="Select a question on the left to start tutoring.",
                 font=FONT_BODY, bg=C["content_bg"], fg=C["text_secondary"],
                 wraplength=340, justify="left").pack(anchor="w", pady=(20, 0))

    def _render_chat_panel(self):
        for w in self._chat_container.winfo_children():
            w.destroy()

        record = self._current_record

        ctx = tk.Frame(self._chat_container, bg=C["card_bg"],
                       highlightbackground=C["border"], highlightthickness=1)
        ctx.pack(fill="x", pady=(0, 12))
        tk.Label(ctx, text=f"Question {record.number}", font=("Segoe UI", 9, "bold"),
                 bg=C["card_bg"], fg=C["accent_blue"]).pack(anchor="w", padx=14, pady=(10, 2))
        tk.Label(ctx, text=record.question, font=FONT_BODY, bg=C["card_bg"], fg=C["text_primary"],
                 wraplength=340, justify="left").pack(anchor="w", padx=14, pady=(0, 8))
        tk.Label(ctx, text=f"Your answer: {record.user_answer or '(none)'}", font=FONT_LABEL,
                 bg=C["card_bg"], fg=C["text_secondary"], wraplength=340,
                 justify="left").pack(anchor="w", padx=14)
        tk.Label(ctx, text=f"Standard answer: {record.correct_answer or '(not available)'}",
                 font=FONT_LABEL, bg=C["card_bg"], fg=C["text_secondary"], wraplength=340,
                 justify="left").pack(anchor="w", padx=14, pady=(0, 10))

        msg_container = tk.Frame(self._chat_container, bg=C["content_bg"],
                                  highlightbackground=C["border"], highlightthickness=1)
        msg_container.pack(fill="both", expand=True)

        canvas = tk.Canvas(msg_container, bg=C["content_bg"], highlightthickness=0)
        vscroll = tk.Scrollbar(msg_container, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vscroll.set)
        vscroll.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        self._msg_frame  = tk.Frame(canvas, bg=C["content_bg"])
        self._msg_canvas = canvas
        window = canvas.create_window((0, 0), window=self._msg_frame, anchor="nw")
        self._msg_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(window, width=e.width))

        for msg in self._threads.get(record.index, []):
            self._add_bubble(msg['role'], msg['content'])

        if not self._threads.get(record.index):
            self._add_bubble(
                'assistant',
                "Ask me anything about this question — why the answer is "
                "what it is, what you might have misunderstood, or how to "
                "approach similar problems.",
            )

        input_row = tk.Frame(self._chat_container, bg=C["content_bg"])
        input_row.pack(fill="x", pady=(10, 0))

        self._input_entry = tk.Entry(input_row, font=FONT_BODY, bg=C["card_bg"], fg=C["text_primary"],
                                      relief="flat", highlightbackground=C["border"], highlightthickness=1)
        self._input_entry.pack(side="left", fill="x", expand=True, ipady=8, ipadx=10)
        self._input_entry.bind("<Return>", lambda _: self._send())

        self._send_btn = tk.Label(input_row, text="Send", font=("Segoe UI", 10, "bold"),
                                   bg=C["accent_blue"], fg="white", padx=16, pady=8, cursor="hand2")
        self._send_btn.pack(side="left", padx=(8, 0))
        self._send_btn.bind("<Button-1>", lambda _: self._send())

    def _add_bubble(self, role: str, text: str):
        is_user = role == "user"
        row = tk.Frame(self._msg_frame, bg=C["content_bg"])
        row.pack(fill="x", padx=10, pady=6, anchor="e" if is_user else "w")

        bubble = tk.Label(row, text=text, font=FONT_BODY,
                           bg=C["user_bubble"] if is_user else C["ai_bubble"],
                           fg="white" if is_user else C["text_primary"],
                           wraplength=300, justify="left", padx=12, pady=8)
        bubble.pack(side="right" if is_user else "left")

        self._msg_frame.update_idletasks()
        self._msg_canvas.yview_moveto(1.0)

    def _send(self):
        if self._waiting or not self._current_record:
            return
        text = self._input_entry.get().strip()
        if not text:
            return

        self._input_entry.delete(0, "end")
        record = self._current_record
        self._threads.setdefault(record.index, [])
        history_before = list(self._threads[record.index])

        self._add_bubble('user', text)
        self._threads[record.index].append({'role': 'user', 'content': text})
        self._set_waiting(True)

        self._runner.eval_thread_message(
            question=record.question,
            user_answer=record.user_answer,
            correct_answer=record.correct_answer,
            follow_up=text,
            history=history_before,
            options=record.options if record.q_type == 'MCQ' else None,
            on_result=lambda reply: self._root.after(0, lambda: self._on_reply(record.index, reply)),
            on_error=lambda err: self._root.after(0, lambda: self._on_error(record.index, err)),
        )

    def _on_reply(self, q_index, reply):
        self._set_waiting(False)
        self._threads.setdefault(q_index, []).append({'role': 'assistant', 'content': reply})
        if self._current_record and self._current_record.index == q_index:
            self._add_bubble('assistant', reply)

    def _on_error(self, q_index, error_msg):
        self._set_waiting(False)
        if self._current_record and self._current_record.index == q_index:
            self._add_bubble('assistant', f"⚠ {error_msg}")

    def _set_waiting(self, waiting: bool):
        self._waiting = waiting
        if hasattr(self, '_send_btn'):
            self._send_btn.config(
                text="…" if waiting else "Send",
                bg=C["text_secondary"] if waiting else C["accent_blue"],
            )
