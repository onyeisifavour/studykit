"""
flashcards_page.py

Flashcard review for StudyKit. Two deck sources (see flashcard_builder.py):

  - "From your quizzes" — questions you missed in past quizzes.
  - "From your library" — Q&A decks parsed from each topic's question banks.

Views:
  - Deck list (grouped by source, scrollable).
  - Study: one card at a time, click to flip, self-rate "Still learning"
    (returns to the deck) or "Got it" (removed from rotation).
  - Summary when a study pass ends.
"""

import tkinter as tk

from .theme import C, FONT_BODY, FONT_LABEL, FONT_H2, FONT_H3, Page
from .. import config
from .. import library_scanner
from ..flashcard_builder import build_all_decks, Deck


class FlashcardsPage(Page):

    def __init__(self, parent):
        super().__init__(parent)
        self._topic_files: list[dict] = []
        self._decks: list[Deck] = []
        self._active_deck: Deck | None = None
        self._cards: list = []
        self._idx = 0
        self._revealed = False
        self._got_count = 0
        self._retry_count = 0
        self._build_shell()

    # ── Shell ─────────────────────────────────────────────────────────────────
    def _build_shell(self):
        header = tk.Frame(self, bg=C["content_bg"])
        header.pack(fill="x", padx=36, pady=(30, 0))

        self._title_lbl = tk.Label(header, text="Flashcards", font=FONT_H2,
                                   bg=C["content_bg"], fg=C["text_primary"])
        self._title_lbl.pack(side="left")

        self._back_btn = tk.Label(header, text="← All Decks", font=("Segoe UI", 9, "bold"),
                                  bg=C["text_secondary"], fg="white", padx=12, pady=5, cursor="hand2")
        self._back_btn.bind("<Button-1>", lambda _: self._render_deck_list())

        tk.Frame(self, bg=C["border"], height=1).pack(fill="x", padx=36, pady=16)

        self._body = tk.Frame(self, bg=C["content_bg"])
        self._body.pack(fill="both", expand=True, padx=36, pady=(0, 30))

    def on_show(self):
        self._load_decks()
        self._render_deck_list()

    def _clear_body(self):
        for w in self._body.winfo_children():
            w.destroy()
        self._back_btn.pack_forget()

    # ── Data ──────────────────────────────────────────────────────────────────
    def _load_decks(self):
        selected = config.get_selected_topics()
        self._topic_files = library_scanner.load_selected_topics(selected) if selected else []
        self._decks = build_all_decks(self._topic_files)

    # ── Deck list ─────────────────────────────────────────────────────────────
    def _render_deck_list(self):
        self._active_deck = None
        self._clear_body()
        self._title_lbl.config(text="Flashcards")

        if not self._decks:
            tk.Label(self._body, text="No decks available yet.", font=FONT_H3,
                     bg=C["content_bg"], fg=C["text_secondary"]).pack(anchor="w", pady=(30, 0))
            tk.Label(self._body,
                     text="Decks appear here from two sources:\n"
                          "  • Questions you missed in past quizzes\n"
                          "  • Q&A decks from your library's question banks\n\n"
                          "Finish a quiz or select topics in Settings to populate decks.",
                     font=FONT_BODY, bg=C["content_bg"], fg=C["text_secondary"],
                     wraplength=520, justify="left").pack(anchor="w", pady=(8, 0))
            return

        canvas = tk.Canvas(self._body, bg=C["content_bg"], highlightthickness=0)
        vscroll = tk.Scrollbar(self._body, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vscroll.set)
        vscroll.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        list_frame = tk.Frame(canvas, bg=C["content_bg"])
        canvas.create_window((0, 0), window=list_frame, anchor="nw")
        list_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        quiz_decks = [d for d in self._decks if d.source == 'quiz']
        lib_decks  = [d for d in self._decks if d.source == 'library']

        if quiz_decks:
            tk.Label(list_frame, text="FROM YOUR QUIZZES", font=("Segoe UI", 8, "bold"),
                     bg=C["content_bg"], fg=C["text_secondary"]).pack(anchor="w", pady=(0, 8))
            for deck in quiz_decks:
                self._make_deck_row(list_frame, deck)

        if lib_decks:
            if quiz_decks:
                tk.Frame(list_frame, bg=C["border"], height=1).pack(fill="x", pady=14)
            tk.Label(list_frame, text="FROM YOUR LIBRARY", font=("Segoe UI", 8, "bold"),
                     bg=C["content_bg"], fg=C["text_secondary"]).pack(anchor="w", pady=(0, 8))
            for deck in lib_decks:
                self._make_deck_row(list_frame, deck)

    def _make_deck_row(self, parent, deck: Deck):
        row = tk.Frame(parent, bg=C["card_bg"], highlightbackground=C["border"],
                       highlightthickness=1, cursor="hand2")
        row.pack(fill="x", pady=4)
        inner = tk.Frame(row, bg=C["card_bg"])
        inner.pack(fill="x", padx=16, pady=10)

        tk.Label(inner, text=deck.title, font=("Segoe UI", 11, "bold"),
                 bg=C["card_bg"], fg=C["text_primary"]).pack(anchor="w")
        subj = f"{deck.subject}  •  " if deck.subject else ""
        tk.Label(inner, text=f"{subj}{deck.size} card{'s' if deck.size != 1 else ''}",
                 font=FONT_LABEL, bg=C["card_bg"], fg=C["text_secondary"]).pack(anchor="w", pady=(2, 0))

        for w in (row, inner):
            w.bind("<Button-1>", lambda _, d=deck: self._open_deck(d))

    # ── Study ─────────────────────────────────────────────────────────────────
    def _open_deck(self, deck: Deck):
        self._active_deck = deck
        self._cards = list(deck.cards)
        self._idx = 0
        self._revealed = False
        self._got_count = 0
        self._retry_count = 0
        self._title_lbl.config(text=deck.title)
        self._back_btn.pack(side="right")
        self._render_card()

    def _render_card(self):
        self._clear_body_keep_back()

        if self._idx >= len(self._cards):
            self._render_summary()
            return

        card = self._cards[self._idx]
        self._revealed = False

        tk.Label(self._body, text=f"Card {self._idx + 1} / {len(self._cards)}   ·   "
                                  f"Got it: {self._got_count}",
                 font=FONT_LABEL, bg=C["content_bg"], fg=C["text_secondary"]).pack(anchor="w")

        card_frame = tk.Frame(self._body, bg=C["card_bg"], highlightbackground=C["border"],
                              highlightthickness=1, cursor="hand2")
        card_frame.pack(fill="both", expand=True, pady=(12, 0))

        tk.Frame(card_frame, bg=C["flashcards"], height=4).pack(fill="x")

        hint = tk.Label(card_frame, text="Click the card to flip it", font=FONT_LABEL,
                        bg=C["card_bg"], fg=C["text_secondary"])
        hint.pack(anchor="ne", padx=16, pady=(10, 0))

        self._card_lbl = tk.Label(
            card_frame, text=card.front, font=("Segoe UI", 12),
            bg=C["card_bg"], fg=C["text_primary"], wraplength=640,
            justify="left", padx=24, pady=20, anchor="n",
        )
        self._card_lbl.pack(fill="both", expand=True)

        for w in (card_frame, self._card_lbl):
            w.bind("<Button-1>", lambda _: self._flip(card))

        self._rating_frame = tk.Frame(self._body, bg=C["content_bg"])

        still_btn = tk.Label(self._rating_frame, text="↻ Still learning",
                             font=("Segoe UI", 10, "bold"), bg=C["incorrect"],
                             fg="white", padx=16, pady=9, cursor="hand2")
        still_btn.pack(side="left")
        still_btn.bind("<Button-1>", lambda _: self._rate(card, got=False))

        got_btn = tk.Label(self._rating_frame, text="✓ Got it",
                           font=("Segoe UI", 10, "bold"), bg=C["correct"],
                           fg="white", padx=16, pady=9, cursor="hand2")
        got_btn.pack(side="left", padx=(8, 0))
        got_btn.bind("<Button-1>", lambda _: self._rate(card, got=True))

    def _flip(self, card):
        if self._revealed:
            return
        self._revealed = True
        self._card_lbl.config(text=card.back, fg=C["text_primary"])
        self._card_lbl.bind("<Button-1>", lambda _: None)   # stop flip on click after reveal
        self._rating_frame.pack(fill="x", pady=(12, 0))

    def _rate(self, card, got: bool):
        if got:
            self._got_count += 1
            self._idx += 1
        else:
            self._retry_count += 1
            self._cards.append(card)
            self._idx += 1
        self._render_card()

    # ── Summary ───────────────────────────────────────────────────────────────
    def _render_summary(self):
        total = self._got_count + self._retry_count
        pct = round((self._got_count / total) * 100) if total else 0

        tk.Label(self._body, text="Deck complete!", font=FONT_H3,
                 bg=C["content_bg"], fg=C["text_primary"]).pack(anchor="w", pady=(40, 6))
        tk.Label(self._body, text=f"Got it: {self._got_count}  ·  Still learning: {self._retry_count}  ·  "
                                  f"{pct}% this pass",
                 font=FONT_BODY, bg=C["content_bg"], fg=C["text_secondary"]).pack(anchor="w")

        ctrl = tk.Frame(self._body, bg=C["content_bg"])
        ctrl.pack(fill="x", pady=(20, 0))

        again_btn = tk.Label(ctrl, text="↻ Review again", font=("Segoe UI", 10, "bold"),
                             bg=C["accent"], fg="white", padx=16, pady=9, cursor="hand2")
        again_btn.pack(side="left")
        again_btn.bind("<Button-1>", lambda _: self._reopen_active_deck())

        done_btn = tk.Label(ctrl, text="All decks →", font=("Segoe UI", 10, "bold"),
                            bg=C["accent_blue"], fg="white", padx=16, pady=9, cursor="hand2")
        done_btn.pack(side="left", padx=(10, 0))
        done_btn.bind("<Button-1>", lambda _: self._render_deck_list())

    def _reopen_active_deck(self):
        if self._active_deck:
            self._open_deck(self._active_deck)

    def _clear_body_keep_back(self):
        for w in self._body.winfo_children():
            w.destroy()
