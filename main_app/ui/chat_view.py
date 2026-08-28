"""
chat_view.py

Pre-quiz chat widget. Embedded inside quiz_page.py's CHAT state.
Uses AgentRunner to communicate with opencode agents:
- Main chat agent for diagnostic conversation
- Background models for research reports

Runs API calls via AgentRunner, which is thread-safe:
this widget wraps every callback with root.after(0, ...) before touching
any Tkinter widget.
"""

import tkinter as tk
from typing import Optional

from .theme import C, FONT_BODY, FONT_LABEL, FONT_H3
from .. import prompts


class ChatView(tk.Frame):
    """
    A self-contained chat widget: message bubbles + input row.

    Usage:
        chat = ChatView(parent, root, agent_runner, topic_files, prefs,
                         on_ready_to_generate=callback)
        chat.pack(...)
        history = chat.get_history()   # for blueprint_generator input
    """

    def __init__(self, parent, root, agent_runner, topic_files, prefs,
                 on_ready_to_generate=None):
        super().__init__(parent, bg=C["content_bg"])
        self._root = root
        self._agent_runner = agent_runner
        self._topic_files = topic_files
        self._prefs = prefs
        self._on_ready = on_ready_to_generate
        self._history: list[dict] = []  # [{'role': 'user'|'assistant', 'content': str}]
        self._teacher_message: Optional[str] = None  # Last AI response for background models
        self._waiting = False
        self._started = False  # Track if Start Chat was clicked
        self._build()

    # ── Build ─────────────────────────────────────────────────────────────────
    def _build(self):
        tk.Label(
            self, text="Let's plan your quiz", font=FONT_H3,
            bg=C["content_bg"], fg=C["text_primary"],
        ).pack(anchor="w", pady=(0, 4))

        tk.Label(
            self, text="Tell the AI what topics, how many questions, and any "
                       "weak areas to prioritise.",
            font=FONT_LABEL, bg=C["content_bg"], fg=C["text_secondary"],
            wraplength=440, justify="left",
        ).pack(anchor="w", pady=(0, 12))

        # Scrollable message area
        msg_container = tk.Frame(self, bg=C["card_bg"],
                                  highlightbackground=C["border"], highlightthickness=1)
        msg_container.pack(fill="both", expand=True)

        self._canvas = tk.Canvas(msg_container, bg=C["card_bg"], highlightthickness=0)
        vscroll = tk.Scrollbar(msg_container, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=vscroll.set)
        vscroll.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)

        self._msg_frame = tk.Frame(self._canvas, bg=C["card_bg"])
        self._canvas_window = self._canvas.create_window((0, 0), window=self._msg_frame, anchor="nw")
        self._msg_frame.bind("<Configure>", self._on_frame_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)

        # Start Chat button (shown initially)
        self._start_frame = tk.Frame(self, bg=C["content_bg"])
        self._start_frame.pack(fill="x", pady=(10, 0))

        self._start_btn = tk.Label(
            self._start_frame, text="Start Chat", font=("Segoe UI", 11, "bold"),
            bg=C["accent_blue"], fg="white", padx=24, pady=10, cursor="hand2",
        )
        self._start_btn.pack(anchor="center")
        self._start_btn.bind("<Button-1>", lambda _: self._on_start_chat())

        # Input row (hidden initially, shown after greeting)
        self._input_frame = tk.Frame(self, bg=C["content_bg"])

        self._input_entry = tk.Entry(
            self._input_frame, font=FONT_BODY, bg=C["card_bg"], fg=C["text_primary"],
            relief="flat", highlightbackground=C["border"], highlightthickness=1,
        )
        self._input_entry.pack(side="left", fill="x", expand=True, ipady=8, ipadx=10)
        self._input_entry.bind("<Return>", lambda _: self._send())

        self._send_btn = tk.Label(
            self._input_frame, text="Send", font=("Segoe UI", 10, "bold"),
            bg=C["accent_blue"], fg="white", padx=16, pady=8, cursor="hand2",
        )
        self._send_btn.pack(side="left", padx=(8, 0))
        self._send_btn.bind("<Button-1>", lambda _: self._send())

        # Generate button (enabled once the AI signals readiness, or manually)
        gen_row = tk.Frame(self, bg=C["content_bg"])
        gen_row.pack(fill="x", pady=(10, 0))

        self._generate_btn = tk.Label(
            gen_row, text="Generate Quiz →", font=("Segoe UI", 10, "bold"),
            bg=C["correct"], fg="white", padx=18, pady=10, cursor="hand2",
        )
        self._generate_btn.pack(side="right")
        self._generate_btn.bind("<Button-1>", lambda _: self._trigger_generate())

    def _on_frame_configure(self, _event):
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self._canvas.itemconfig(self._canvas_window, width=event.width)

    # ── Start Chat ────────────────────────────────────────────────────────────
    def _on_start_chat(self):
        """Send initial signal to AI, get greeting."""
        if self._waiting:
            return
        self._started = True
        self._set_waiting(True)

        # Disable start button
        self._start_btn.config(state="disabled", bg=C["text_secondary"])

        # Call main chat agent with start signal
        self._agent_runner.call_main_chat(
            user_message="START",
            topic_files=self._topic_files,
            prefs=self._prefs,
            teacher_message=None,
            on_result=lambda reply: self._root.after(0, lambda: self._on_greeting(reply)),
            on_error=lambda err: self._root.after(0, lambda: self._on_start_error(err)),
        )

    def _on_greeting(self, reply: str):
        """Display greeting, enable input."""
        self._set_waiting(False)
        self._history.append({'role': 'assistant', 'content': reply})
        self._add_bubble("assistant", reply)

        # Store for background models
        self._teacher_message = reply

        # Toggle UI: hide Start Chat, show input
        self._start_frame.pack_forget()
        self._input_frame.pack(fill="x", pady=(10, 0))
        self._input_entry.focus_set()

    def _on_start_error(self, error_msg: str):
        """Handle error during start."""
        self._set_waiting(False)
        self._start_btn.config(state="normal", bg=C["accent_blue"])
        self._add_bubble("assistant", f"⚠ {error_msg}")

    # ── Messaging ──────────────────────────────────────────────────────────────
    def _send(self):
        if self._waiting:
            return
        text = self._input_entry.get().strip()
        if not text:
            return

        self._input_entry.delete(0, "end")
        self._add_bubble("user", text)
        self._history.append({'role': 'user', 'content': text})
        self._set_waiting(True)

        # Call main chat agent
        self._agent_runner.call_main_chat(
            user_message=text,
            topic_files=self._topic_files,
            prefs=self._prefs,
            teacher_message=self._teacher_message,
            on_result=lambda reply: self._root.after(0, lambda: self._on_reply(reply, text)),
            on_error=lambda err: self._root.after(0, lambda: self._on_error(err)),
        )

    def _on_reply(self, reply: str, student_message: str):
        self._set_waiting(False)
        self._history.append({'role': 'assistant', 'content': reply})
        self._add_bubble("assistant", reply)

        # Send to background models (async, don't wait)
        teacher = self._teacher_message
        self._teacher_message = reply  # Update for next turn

        # Build topic context from concept blocks
        topic_context = prompts.build_multi_topic_concepts(self._topic_files) if self._topic_files else ""

        self._agent_runner.send_to_background_models(
            teacher_message=teacher,
            student_message=student_message,
            topic_digest=topic_context,
        )

    def _on_error(self, error_msg: str):
        self._set_waiting(False)
        self._add_bubble("assistant", f"⚠ {error_msg}")

    def _set_waiting(self, waiting: bool):
        self._waiting = waiting
        if self._started:
            # After start: toggle send button
            self._send_btn.config(
                text="…" if waiting else "Send",
                bg=C["text_secondary"] if waiting else C["accent_blue"],
            )
        else:
            # Before start: toggle start button
            self._start_btn.config(
                text="…" if waiting else "Start Chat",
                bg=C["text_secondary"] if waiting else C["accent_blue"],
            )

    def _trigger_generate(self):
        if self._on_ready:
            self._on_ready()

    # ── Bubble rendering ──────────────────────────────────────────────────────
    def _add_bubble(self, role: str, text: str):
        is_user = role == "user"
        row = tk.Frame(self._msg_frame, bg=C["card_bg"])
        row.pack(fill="x", padx=12, pady=6, anchor="e" if is_user else "w")

        bubble = tk.Label(
            row, text=text, font=FONT_BODY,
            bg=C["user_bubble"] if is_user else C["ai_bubble"],
            fg="white" if is_user else C["text_primary"],
            wraplength=340, justify="left",
            padx=12, pady=8,
        )
        bubble.pack(side="right" if is_user else "left")

        self._msg_frame.update_idletasks()
        self._canvas.yview_moveto(1.0)

    # ── Public API ────────────────────────────────────────────────────────────
    def get_history(self) -> list[dict]:
        """Returns the full chat history for blueprint generation input."""
        return list(self._history)
