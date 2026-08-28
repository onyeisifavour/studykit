"""
main_window.py — Root Tkinter window with collapsible sidebar navigation.
Hosts all page frames and controls navigation between them.

This file owns: Sidebar, HomePage, SettingsPage, MainWindow (the shell).
Quiz / Review / Tutor pages live in their own modules and are imported below.
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from .theme import C, FONT_BODY, FONT_LABEL, FONT_H1, FONT_H2, FONT_H3, Page, \
    SIDEBAR_EXPANDED, SIDEBAR_COLLAPSED
from .. import config
from ..api_client import ApiClient, CLIBridgeClient
from ..evaluation_runner import EvaluationRunner
from .. import library_scanner


# ── Nav item definition ───────────────────────────────────────────────────────
NAV_ITEMS = [
    {"id": "home",       "label": "Home",       "icon": "⌂"},
    {"id": "quiz",       "label": "Quiz",       "icon": "✎"},
    {"id": "flashcards", "label": "Flashcards", "icon": "🃏"},
    {"id": "review",     "label": "Review",     "icon": "◷"},
    {"id": "tutor",      "label": "Tutor",      "icon": "💬"},
    {"id": "settings",   "label": "Settings",   "icon": "⚙"},
]


# ── Sidebar ───────────────────────────────────────────────────────────────────
class Sidebar(tk.Frame):
    def __init__(self, parent, on_navigate, **kwargs):
        super().__init__(parent, bg=C["sidebar_bg"], **kwargs)
        self._on_navigate = on_navigate
        self._expanded = True
        self._active_id = "home"
        self._buttons = {}
        self._build()

    def _build(self):
        toggle_row = tk.Frame(self, bg=C["sidebar_bg"])
        toggle_row.pack(fill="x", pady=(12, 4))

        self._toggle_btn = tk.Label(
            toggle_row, text="☰", font=("Segoe UI", 14),
            bg=C["sidebar_bg"], fg=C["icon_inactive"],
            cursor="hand2", padx=14, pady=6,
        )
        self._toggle_btn.pack(side="left")
        self._toggle_btn.bind("<Button-1>", lambda _: self.toggle())
        self._toggle_btn.bind("<Enter>",    lambda _: self._toggle_btn.config(fg=C["icon_active"]))
        self._toggle_btn.bind("<Leave>",    lambda _: self._toggle_btn.config(fg=C["icon_inactive"]))

        self._title_lbl = tk.Label(
            toggle_row, text="StudyKit", font=("Segoe UI", 13, "bold"),
            bg=C["sidebar_bg"], fg=C["icon_active"],
        )
        self._title_lbl.pack(side="left", padx=(2, 0))

        tk.Frame(self, bg=C["sidebar_hover"], height=1).pack(fill="x", padx=10, pady=(4, 8))

        for item in NAV_ITEMS:
            self._make_nav_button(item)

        tk.Frame(self, bg=C["sidebar_bg"]).pack(fill="both", expand=True)
        self._ver_lbl = tk.Label(
            self, text="v0.2", font=FONT_LABEL,
            bg=C["sidebar_bg"], fg=C["icon_inactive"],
        )
        self._ver_lbl.pack(pady=(0, 12))

        self._apply_active(self._active_id)

    def _make_nav_button(self, item):
        row = tk.Frame(self, bg=C["sidebar_bg"], cursor="hand2")
        row.pack(fill="x")

        bar = tk.Frame(row, bg=C["sidebar_bg"], width=3)
        bar.pack(side="left", fill="y")

        icon_lbl = tk.Label(
            row, text=item["icon"], font=("Segoe UI", 13),
            bg=C["sidebar_bg"], fg=C["icon_inactive"],
            width=3, anchor="center",
        )
        icon_lbl.pack(side="left", pady=10)

        text_lbl = tk.Label(
            row, text=item["label"], font=FONT_BODY,
            bg=C["sidebar_bg"], fg=C["label_inactive"],
            anchor="w",
        )
        text_lbl.pack(side="left", fill="x", expand=True)

        self._buttons[item["id"]] = {"row": row, "bar": bar, "icon": icon_lbl, "text": text_lbl}

        for widget in (row, icon_lbl, text_lbl):
            widget.bind("<Button-1>", lambda _, i=item["id"]: self._click(i))
            widget.bind("<Enter>",    lambda _, i=item["id"]: self._hover(i, True))
            widget.bind("<Leave>",    lambda _, i=item["id"]: self._hover(i, False))

    def _click(self, page_id):
        self._active_id = page_id
        self._apply_active(page_id)
        self._on_navigate(page_id)

    def _hover(self, page_id, entering):
        if page_id == self._active_id:
            return
        btn = self._buttons[page_id]
        color = C["sidebar_hover"] if entering else C["sidebar_bg"]
        for w in (btn["row"], btn["icon"], btn["text"], btn["bar"]):
            w.config(bg=color)
        btn["icon"].config(fg=C["icon_active"] if entering else C["icon_inactive"])
        btn["text"].config(fg=C["label_active"] if entering else C["label_inactive"])

    def _apply_active(self, active_id):
        for pid, btn in self._buttons.items():
            is_active = pid == active_id
            bg = C["active_bg"] if is_active else C["sidebar_bg"]
            for w in (btn["row"], btn["icon"], btn["text"]):
                w.config(bg=bg)
            btn["bar"].config(bg=C["active_bar"] if is_active else bg)
            btn["icon"].config(fg=C["icon_active"] if is_active else C["icon_inactive"])
            btn["text"].config(fg=C["label_active"] if is_active else C["label_inactive"])

    def toggle(self):
        self._expanded = not self._expanded
        w = SIDEBAR_EXPANDED if self._expanded else SIDEBAR_COLLAPSED
        self.config(width=w)
        if self._expanded:
            self._title_lbl.pack(side="left", padx=(2, 0))
            self._ver_lbl.config(text="v0.2")
            for btn in self._buttons.values():
                btn["text"].pack(side="left", fill="x", expand=True)
        else:
            self._title_lbl.pack_forget()
            self._ver_lbl.config(text="")
            for btn in self._buttons.values():
                btn["text"].pack_forget()


# ── Home page ─────────────────────────────────────────────────────────────────
class HomePage(Page):
    def __init__(self, parent, on_navigate):
        super().__init__(parent)
        self._on_navigate = on_navigate
        self._build()

    def _build(self):
        header = tk.Frame(self, bg=C["content_bg"])
        header.pack(fill="x", padx=40, pady=(40, 0))

        tk.Label(header, text="Good to see you.", font=FONT_H1,
                 bg=C["content_bg"], fg=C["text_primary"]).pack(anchor="w")
        tk.Label(header, text="Where would you like to start?", font=FONT_BODY,
                 bg=C["content_bg"], fg=C["text_secondary"]).pack(anchor="w", pady=(4, 0))

        tk.Frame(self, bg=C["border"], height=1).pack(fill="x", padx=40, pady=24)

        cards_frame = tk.Frame(self, bg=C["content_bg"])
        cards_frame.pack(fill="x", padx=40)

        self._make_card(cards_frame, "✎", "Quiz",
            "Chat with the AI about what you want to study, then take a "
            "generated quiz with live evaluation.",
            lambda: self._on_navigate("quiz"), C["accent_blue"])

        self._make_card(cards_frame, "🃏", "Flashcards",
            "Review the questions you've missed and browse topic Q&A decks "
            "built from your library.",
            lambda: self._on_navigate("flashcards"), C["flashcards"])

        self._make_card(cards_frame, "◷", "Review",
            "Revisit a completed quiz. See every question, your answers, "
            "and the correct answers side by side.",
            lambda: self._on_navigate("review"), C["accent"])

        self._make_card(cards_frame, "💬", "Tutor",
            "Discuss specific questions from a past quiz with the AI "
            "for deeper, focused tutoring.",
            lambda: self._on_navigate("tutor"), C["correct"])

    def _make_card(self, parent, icon, title, desc, action, accent):
        card = tk.Frame(parent, bg=C["card_bg"],
                         highlightbackground=C["border"], highlightthickness=1, cursor="hand2")
        card.pack(side="left", fill="both", expand=True, padx=(0, 16), pady=4)

        tk.Frame(card, bg=accent, height=4).pack(fill="x")
        inner = tk.Frame(card, bg=C["card_bg"])
        inner.pack(fill="both", expand=True, padx=24, pady=20)

        tk.Label(inner, text=icon, font=("Segoe UI", 26),
                 bg=C["card_bg"], fg=accent).pack(anchor="w")
        tk.Label(inner, text=title, font=FONT_H3,
                 bg=C["card_bg"], fg=C["text_primary"]).pack(anchor="w", pady=(8, 4))
        tk.Label(inner, text=desc, font=FONT_LABEL, bg=C["card_bg"], fg=C["text_secondary"],
                 wraplength=220, justify="left").pack(anchor="w")

        btn = tk.Label(inner, text=f"Open {title} →", font=("Segoe UI", 9, "bold"),
                        bg=C["card_bg"], fg=accent, cursor="hand2")
        btn.pack(anchor="w", pady=(16, 0))

        for w in (card, inner, btn):
            w.bind("<Button-1>", lambda _: action())


# ── Settings page ─────────────────────────────────────────────────────────────
class SettingsPage(Page):
    """
    Three sections:
      1. API Keys — up to 4 GROQ keys + 4 OpenRouter keys, plus model names.
      2. Learning Library — browse root, tree of Subject > Topic with
         checkbox-style selection, saved to config.
      3. Evaluation default — ON/OFF toggle used as the default for new quizzes.
    """
    def __init__(self, parent, api_client: ApiClient):
        super().__init__(parent)
        self._api_client = api_client
        self._library_tree = None          # library_scanner.LibraryTree
        self._checked_paths: set[str] = set(config.get_selected_topics())
        self._tree_item_to_path: dict[str, str] = {}
        self._build()
        self._load_saved_config()

    # ── Build ─────────────────────────────────────────────────────────────────
    def _build(self):
        canvas = tk.Canvas(self, bg=C["content_bg"], highlightthickness=0)
        vscroll = tk.Scrollbar(self, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vscroll.set)
        vscroll.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        body = tk.Frame(canvas, bg=C["content_bg"])
        canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-e.delta / 120), "units"))

        tk.Label(body, text="Settings", font=FONT_H2,
                 bg=C["content_bg"], fg=C["text_primary"]).pack(anchor="w", padx=40, pady=(40, 4))
        tk.Label(body, text="Configure API access and your learning library.", font=FONT_LABEL,
                 bg=C["content_bg"], fg=C["text_secondary"]).pack(anchor="w", padx=40)
        tk.Frame(body, bg=C["border"], height=1).pack(fill="x", padx=40, pady=20)

        self._build_api_keys_section(body)
        tk.Frame(body, bg=C["border"], height=1).pack(fill="x", padx=40, pady=24)
        self._build_library_section(body)
        tk.Frame(body, bg=C["border"], height=1).pack(fill="x", padx=40, pady=24)
        self._build_question_types_section(body)
        tk.Frame(body, bg=C["border"], height=1).pack(fill="x", padx=40, pady=24)
        self._build_evaluation_section(body)

        tk.Frame(body, bg=C["content_bg"], height=30).pack()

    # ── API keys section ───────────────────────────────────────────────────────
    def _build_api_keys_section(self, parent):
        tk.Label(parent, text="PROVIDER MODE", font=("Segoe UI", 8, "bold"),
                 bg=C["content_bg"], fg=C["text_secondary"]).pack(anchor="w", padx=40, pady=(0, 4))

        mode_row = tk.Frame(parent, bg=C["content_bg"])
        mode_row.pack(fill="x", padx=40, pady=(0, 12))

        self._mode_api_btn = tk.Label(
            mode_row, text="API (Direct)", font=("Segoe UI", 10, "bold"),
            bg=C["accent_blue"], fg="white", padx=16, pady=8, cursor="hand2")
        self._mode_api_btn.pack(side="left")
        self._mode_api_btn.bind("<Button-1>", lambda _: self._set_provider_mode('api'))

        self._mode_cli_btn = tk.Label(
            mode_row, text="CLI Bridge (opencode)", font=("Segoe UI", 10, "bold"),
            bg=C["text_secondary"], fg="white", padx=16, pady=8, cursor="hand2")
        self._mode_cli_btn.pack(side="left", padx=(10, 0))
        self._mode_cli_btn.bind("<Button-1>", lambda _: self._set_provider_mode('cli_bridge'))

        self._mode_desc = tk.Label(
            parent, text="", font=FONT_LABEL,
            bg=C["content_bg"], fg=C["text_secondary"],
            wraplength=560, justify="left")
        self._mode_desc.pack(anchor="w", padx=40, pady=(0, 12))

        # ── Mode container ────────────────────────────────────────────────────
        # BUGFIX: previously self._api_settings_frame / self._cli_settings_frame
        # were toggled with pack()/pack_forget() directly inside `parent`, which
        # also holds the Library and Evaluation sections below them. pack()
        # re-appends a re-shown widget to the END of its parent's packing order
        # rather than restoring its original slot — so each toggle shoved the
        # frame further down, past the other sections, making it look like the
        # fields had vanished. Fix: give both frames their own dedicated
        # container and stack them in the SAME grid cell. grid_remove() (unlike
        # pack_forget()) remembers a widget's exact grid configuration, so
        # re-gridding restores it perfectly every time — no reordering possible.
        self._mode_container = tk.Frame(parent, bg=C["content_bg"])
        self._mode_container.pack(fill="x")
        self._mode_container.grid_columnconfigure(0, weight=1)

        # ── API settings container (shown when mode=api) ────────────────────────
        self._api_settings_frame = tk.Frame(self._mode_container, bg=C["content_bg"])

        tk.Label(self._api_settings_frame, text="API KEYS", font=("Segoe UI", 8, "bold"),
                 bg=C["content_bg"], fg=C["text_secondary"]).pack(anchor="w", pady=(0, 4))
        tk.Label(self._api_settings_frame, text="Up to 4 keys per provider. The app tries each in "
                                                  "order and fails over automatically.",
                 font=FONT_LABEL, bg=C["content_bg"], fg=C["text_secondary"],
                 wraplength=560, justify="left").pack(anchor="w", pady=(0, 12))

        row = tk.Frame(self._api_settings_frame, bg=C["content_bg"])
        row.pack(fill="x")

        groq_col = tk.Frame(row, bg=C["content_bg"])
        groq_col.pack(side="left", fill="both", expand=True, padx=(0, 12))
        or_col = tk.Frame(row, bg=C["content_bg"])
        or_col.pack(side="left", fill="both", expand=True, padx=(12, 0))

        tk.Label(groq_col, text="GROQ", font=("Segoe UI", 9, "bold"),
                 bg=C["content_bg"], fg=C["accent_blue"]).pack(anchor="w", pady=(0, 6))
        self._groq_entries = [self._key_entry_row(groq_col, f"Key {i+1}") for i in range(4)]

        tk.Label(groq_col, text="Model", font=FONT_LABEL,
                 bg=C["content_bg"], fg=C["text_secondary"]).pack(anchor="w", pady=(8, 2))
        self._groq_model_entry = tk.Entry(groq_col, font=FONT_BODY, bg=C["card_bg"],
                                           fg=C["text_primary"], relief="flat",
                                           highlightbackground=C["border"], highlightthickness=1)
        self._groq_model_entry.pack(fill="x", ipady=6, ipadx=8)

        tk.Label(or_col, text="OPENROUTER", font=("Segoe UI", 9, "bold"),
                 bg=C["content_bg"], fg=C["accent"]).pack(anchor="w", pady=(0, 6))
        self._or_entries = [self._key_entry_row(or_col, f"Key {i+1}") for i in range(4)]

        tk.Label(or_col, text="Model", font=FONT_LABEL,
                 bg=C["content_bg"], fg=C["text_secondary"]).pack(anchor="w", pady=(8, 2))
        self._or_model_entry = tk.Entry(or_col, font=FONT_BODY, bg=C["card_bg"],
                                         fg=C["text_primary"], relief="flat",
                                         highlightbackground=C["border"], highlightthickness=1)
        self._or_model_entry.pack(fill="x", ipady=6, ipadx=8)

        tk.Frame(self._api_settings_frame, bg=C["border"], height=1).pack(fill="x", pady=(14, 10))

        custom_frame = tk.Frame(self._api_settings_frame, bg=C["content_bg"])
        custom_frame.pack(fill="x")

        tk.Label(custom_frame, text="CUSTOM (OpenAI-compatible)", font=("Segoe UI", 9, "bold"),
                 bg=C["content_bg"], fg=C["correct"]).pack(anchor="w", pady=(0, 6))
        tk.Label(custom_frame, text="Any provider with an OpenAI-compatible /chat/completions endpoint.",
                 font=FONT_LABEL, bg=C["content_bg"], fg=C["text_secondary"],
                 wraplength=560, justify="left").pack(anchor="w", pady=(0, 8))

        url_row = tk.Frame(custom_frame, bg=C["content_bg"])
        url_row.pack(fill="x", pady=2)
        tk.Label(url_row, text="URL", font=FONT_LABEL, bg=C["content_bg"],
                 fg=C["text_secondary"], width=6, anchor="w").pack(side="left")
        self._custom_url_entry = tk.Entry(url_row, font=FONT_BODY, bg=C["card_bg"],
                                           fg=C["text_primary"], relief="flat",
                                           highlightbackground=C["border"], highlightthickness=1)
        self._custom_url_entry.pack(side="left", fill="x", expand=True, ipady=5, ipadx=6)

        key_row = tk.Frame(custom_frame, bg=C["content_bg"])
        key_row.pack(fill="x", pady=2)
        tk.Label(key_row, text="Key", font=FONT_LABEL, bg=C["content_bg"],
                 fg=C["text_secondary"], width=6, anchor="w").pack(side="left")
        self._custom_key_entry = tk.Entry(key_row, font=FONT_BODY, show="•", bg=C["card_bg"],
                                           fg=C["text_primary"], relief="flat",
                                           highlightbackground=C["border"], highlightthickness=1)
        self._custom_key_entry.pack(side="left", fill="x", expand=True, ipady=5, ipadx=6)

        model_row = tk.Frame(custom_frame, bg=C["content_bg"])
        model_row.pack(fill="x", pady=2)
        tk.Label(model_row, text="Model", font=FONT_LABEL, bg=C["content_bg"],
                 fg=C["text_secondary"], width=6, anchor="w").pack(side="left")
        self._custom_model_entry = tk.Entry(model_row, font=FONT_BODY, bg=C["card_bg"],
                                             fg=C["text_primary"], relief="flat",
                                             highlightbackground=C["border"], highlightthickness=1)
        self._custom_model_entry.pack(side="left", fill="x", expand=True, ipady=5, ipadx=6)

        save_row = tk.Frame(self._api_settings_frame, bg=C["content_bg"])
        save_row.pack(fill="x", pady=(14, 0))
        save_btn = tk.Label(save_row, text="Save API Keys", font=("Segoe UI", 10, "bold"),
                             bg=C["accent_blue"], fg="white", padx=16, pady=8, cursor="hand2")
        save_btn.pack(side="left")
        save_btn.bind("<Button-1>", lambda _: self._save_api_keys())

        self._api_status = tk.Label(save_row, text="", font=FONT_LABEL,
                                     bg=C["content_bg"], fg=C["correct"])
        self._api_status.pack(side="left", padx=(12, 0))

        self._api_settings_frame.grid(row=0, column=0, sticky="nsew", padx=40)

        # ── CLI Bridge settings container (shown when mode=cli_bridge) ───────────
        self._cli_settings_frame = tk.Frame(self._mode_container, bg=C["content_bg"])

        tk.Label(self._cli_settings_frame, text="CLI BRIDGE (opencode)", font=("Segoe UI", 8, "bold"),
                 bg=C["content_bg"], fg=C["text_secondary"]).pack(anchor="w", pady=(0, 4))
        tk.Label(self._cli_settings_frame,
                 text="Uses the local opencode CLI. No API keys needed — "
                      "inherits your terminal login and credits.",
                 font=FONT_LABEL, bg=C["content_bg"], fg=C["text_secondary"],
                 wraplength=560, justify="left").pack(anchor="w", pady=(0, 12))

        cli_model_row = tk.Frame(self._cli_settings_frame, bg=C["content_bg"])
        cli_model_row.pack(fill="x")
        tk.Label(cli_model_row, text="Model", font=FONT_LABEL, bg=C["content_bg"],
                 fg=C["text_secondary"], width=10, anchor="w").pack(side="left")
        self._cli_model_entry = tk.Entry(cli_model_row, font=FONT_BODY, bg=C["card_bg"],
                                          fg=C["text_primary"], relief="flat",
                                          highlightbackground=C["border"], highlightthickness=1)
        self._cli_model_entry.pack(side="left", fill="x", expand=True, ipady=6, ipadx=8)

        tk.Label(self._cli_settings_frame, text="Format: provider/model  (e.g. opencode/big-pickle)",
                 font=FONT_LABEL, bg=C["content_bg"], fg=C["text_secondary"]).pack(
                     anchor="w", pady=(4, 0))

        cli_save_row = tk.Frame(self._cli_settings_frame, bg=C["content_bg"])
        cli_save_row.pack(fill="x", pady=(14, 0))
        cli_save_btn = tk.Label(cli_save_row, text="Save CLI Settings", font=("Segoe UI", 10, "bold"),
                                 bg=C["accent_blue"], fg="white", padx=16, pady=8, cursor="hand2")
        cli_save_btn.pack(side="left")
        cli_save_btn.bind("<Button-1>", lambda _: self._save_cli_settings())

        self._cli_status = tk.Label(cli_save_row, text="", font=FONT_LABEL,
                                     bg=C["content_bg"], fg=C["correct"])
        self._cli_status.pack(side="left", padx=(12, 0))

        self._cli_settings_frame.grid(row=0, column=0, sticky="nsew", padx=40)
        self._cli_settings_frame.grid_remove()   # start hidden; _load_saved_config picks the real mode

    def _key_entry_row(self, parent, label):
        row = tk.Frame(parent, bg=C["content_bg"])
        row.pack(fill="x", pady=2)
        tk.Label(row, text=label, font=FONT_LABEL, bg=C["content_bg"],
                 fg=C["text_secondary"], width=6, anchor="w").pack(side="left")
        entry = tk.Entry(row, font=FONT_BODY, show="•", bg=C["card_bg"], fg=C["text_primary"],
                          relief="flat", highlightbackground=C["border"], highlightthickness=1)
        entry.pack(side="left", fill="x", expand=True, ipady=5, ipadx=6)
        return entry

    def _save_api_keys(self):
        groq_keys = [e.get().strip() for e in self._groq_entries]
        or_keys   = [e.get().strip() for e in self._or_entries]
        groq_model = self._groq_model_entry.get().strip() or None
        or_model   = self._or_model_entry.get().strip() or None
        custom_url   = self._custom_url_entry.get().strip()
        custom_key   = self._custom_key_entry.get().strip()
        custom_model = self._custom_model_entry.get().strip()

        config.update({
            'groq_keys':       groq_keys,
            'openrouter_keys': or_keys,
            'groq_model':      groq_model,
            'openrouter_model':or_model,
            'custom_api_url':  custom_url,
            'custom_api_key':  custom_key,
            'custom_model':    custom_model,
        })
        self._sync_client_to_mode()
        n_active = sum(1 for k in groq_keys + or_keys if k)
        if custom_url and custom_key:
            n_active += 1
        self._api_status.config(text=f"✓ Saved — {n_active} key(s) active")

    def _save_cli_settings(self):
        model = self._cli_model_entry.get().strip() or 'opencode/big-pickle'
        config.save_cli_model(model)
        self._sync_client_to_mode()
        self._cli_status.config(text=f"✓ Saved — model: {model}")

    def _set_provider_mode(self, mode: str):
        config.save_provider_mode(mode)
        self._apply_provider_mode(mode)

    def _apply_provider_mode(self, mode: str):
        is_api = mode == 'api'
        self._mode_api_btn.config(bg=C["accent_blue"] if is_api else C["text_secondary"])
        self._mode_cli_btn.config(bg=C["accent"] if not is_api else C["text_secondary"])

        if is_api:
            self._mode_desc.config(
                text="App makes direct HTTP requests to GROQ, OpenRouter, or a custom API.")
            self._cli_settings_frame.grid_remove()
            self._api_settings_frame.grid()   # grid_remove() remembers the original config — no args needed
        else:
            self._mode_desc.config(
                text="App delegates to local opencode CLI — no API keys needed.")
            self._api_settings_frame.grid_remove()
            self._cli_settings_frame.grid()

        self._sync_client_to_mode()

    def _sync_client_to_mode(self):
        """Swaps the active client on the shared EvaluationRunner + Settings."""
        mode = config.get_provider_mode()
        if mode == 'cli_bridge':
            model = config.get_cli_model() or 'opencode/big-pickle'
            client = CLIBridgeClient(model=model)
        else:
            groq_keys = [e.get().strip() for e in self._groq_entries]
            or_keys   = [e.get().strip() for e in self._or_entries]
            client = ApiClient(
                groq_keys=groq_keys, openrouter_keys=or_keys,
                groq_model=self._groq_model_entry.get().strip() or None,
                openrouter_model=self._or_model_entry.get().strip() or None,
                custom_url=self._custom_url_entry.get().strip(),
                custom_key=self._custom_key_entry.get().strip(),
                custom_model=self._custom_model_entry.get().strip(),
            )

        self._api_client = client
        # Update the runner and all pages that hold a reference
        if hasattr(self, '_runner_ref'):
            self._runner_ref._api = client
        if hasattr(self, '_quiz_page_ref'):
            self._quiz_page_ref._api = client

    # ── Library section ─────────────────────────────────────────────────────────
    def _build_library_section(self, parent):
        tk.Label(parent, text="LEARNING LIBRARY", font=("Segoe UI", 8, "bold"),
                 bg=C["content_bg"], fg=C["text_secondary"]).pack(anchor="w", padx=40, pady=(0, 6))

        path_row = tk.Frame(parent, bg=C["content_bg"])
        path_row.pack(fill="x", padx=40)

        self._root_entry = tk.Entry(path_row, font=FONT_BODY, bg=C["card_bg"], fg=C["text_primary"],
                                     relief="flat", highlightbackground=C["border"], highlightthickness=1)
        self._root_entry.pack(side="left", fill="x", expand=True, ipady=8, ipadx=10)

        browse_btn = tk.Label(path_row, text="Browse", font=("Segoe UI", 10, "bold"),
                               bg=C["text_secondary"], fg="white", padx=16, pady=8, cursor="hand2")
        browse_btn.pack(side="left", padx=(10, 0))
        browse_btn.bind("<Button-1>", lambda _: self._browse_root())

        scan_btn = tk.Label(path_row, text="Scan", font=("Segoe UI", 10, "bold"),
                             bg=C["accent_blue"], fg="white", padx=16, pady=8, cursor="hand2")
        scan_btn.pack(side="left", padx=(8, 0))
        scan_btn.bind("<Button-1>", lambda _: self._scan_library())

        self._scan_status = tk.Label(parent, text="", font=FONT_LABEL,
                                      bg=C["content_bg"], fg=C["text_secondary"])
        self._scan_status.pack(anchor="w", padx=40, pady=(6, 10))

        tree_frame = tk.Frame(parent, bg=C["content_bg"])
        tree_frame.pack(fill="x", padx=40)

        style = ttk.Style()
        style.configure("Lib.Treeview", rowheight=26, font=FONT_BODY)

        self._tree = ttk.Treeview(tree_frame, style="Lib.Treeview", height=10,
                                   show="tree", selectmode="none")
        self._tree.pack(side="left", fill="both", expand=True)
        tree_scroll = tk.Scrollbar(tree_frame, orient="vertical", command=self._tree.yview)
        tree_scroll.pack(side="left", fill="y")
        self._tree.configure(yscrollcommand=tree_scroll.set)
        self._tree.bind("<Button-1>", self._on_tree_click)

        apply_row = tk.Frame(parent, bg=C["content_bg"])
        apply_row.pack(fill="x", padx=40, pady=(10, 0))

        apply_btn = tk.Label(apply_row, text="Save Selection", font=("Segoe UI", 10, "bold"),
                              bg=C["correct"], fg="white", padx=16, pady=8, cursor="hand2")
        apply_btn.pack(side="left")
        apply_btn.bind("<Button-1>", lambda _: self._save_selection())

        self._selection_status = tk.Label(apply_row, text="", font=FONT_LABEL,
                                           bg=C["content_bg"], fg=C["correct"])
        self._selection_status.pack(side="left", padx=(12, 0))

    def _browse_root(self):
        folder = filedialog.askdirectory(title="Select learning library root (X/)")
        if folder:
            self._root_entry.delete(0, "end")
            self._root_entry.insert(0, folder)
            self._scan_library()

    def _scan_library(self):
        root_path = self._root_entry.get().strip()
        if not root_path:
            self._scan_status.config(text="Enter or browse to a library folder first.", fg=C["incorrect"])
            return
        try:
            self._library_tree = library_scanner.scan_library(root_path)
        except FileNotFoundError as e:
            self._scan_status.config(text=str(e), fg=C["incorrect"])
            return

        config.save_library_root(root_path)
        self._populate_tree()
        n_topics = len(self._library_tree.valid_topics())
        self._scan_status.config(
            text=f"✓ Found {n_topics} valid topic(s) across "
                 f"{len(self._library_tree.subjects)} subject(s)",
            fg=C["correct"],
        )

    def _populate_tree(self):
        self._tree.delete(*self._tree.get_children())
        self._tree_item_to_path.clear()
        if not self._library_tree:
            return

        for subject in self._library_tree.subject_names():
            subj_id = self._tree.insert("", "end", text=f"📁 {subject}", open=True)
            for topic_name in self._library_tree.topic_names(subject):
                topic = self._library_tree.get_topic(subject, topic_name)
                path_str = str(topic.folder_path)
                checked = path_str in self._checked_paths
                box = "☑" if checked else "☐"
                invalid_tag = "" if topic.is_valid else "  ⚠ missing files"
                label = f"{box} {topic_name}{invalid_tag}"
                item_id = self._tree.insert(subj_id, "end", text=label)
                self._tree_item_to_path[item_id] = path_str

    def _on_tree_click(self, event):
        item_id = self._tree.identify_row(event.y)
        if item_id not in self._tree_item_to_path:
            return  # clicked a subject header, not a topic leaf

        path_str = self._tree_item_to_path[item_id]
        if path_str in self._checked_paths:
            self._checked_paths.discard(path_str)
        else:
            self._checked_paths.add(path_str)
        self._populate_tree()

    def _save_selection(self):
        config.save_selected_topics(sorted(self._checked_paths))
        self._selection_status.config(text=f"✓ {len(self._checked_paths)} topic(s) selected")

    # ── Question types section ────────────────────────────────────────────────
    def _build_question_types_section(self, parent):
        tk.Label(parent, text="QUESTION TYPES", font=("Segoe UI", 8, "bold"),
                 bg=C["content_bg"], fg=C["text_secondary"]).pack(anchor="w", padx=40, pady=(0, 6))
        tk.Label(parent,
                 text="Select which question types to include. Each section "
                      "(Objective/Theory) can have simulation and/or non-simulation questions.",
                 font=FONT_LABEL, bg=C["content_bg"], fg=C["text_secondary"],
                 wraplength=560, justify="left").pack(anchor="w", padx=40, pady=(0, 10))

        # Section A (Objective)
        self._section_a_frame = tk.Frame(parent, bg=C["content_bg"])
        self._section_a_frame.pack(fill="x", padx=40, pady=(0, 6))
        
        tk.Label(self._section_a_frame, text="Section A (Objective)", font=("Segoe UI", 10, "bold"),
                 bg=C["content_bg"], fg=C["accent_blue"]).pack(anchor="w", pady=(0, 4))
        
        section_a_sub = tk.Frame(self._section_a_frame, bg=C["content_bg"])
        section_a_sub.pack(anchor="w", padx=(20, 0))
        
        self._section_a_sim_var = tk.BooleanVar(value=True)
        self._section_a_nonsim_var = tk.BooleanVar(value=True)
        
        tk.Checkbutton(
            section_a_sub, text="Simulation", variable=self._section_a_sim_var,
            font=FONT_BODY, bg=C["content_bg"], fg=C["text_primary"],
            selectcolor=C["card_bg"], activebackground=C["content_bg"],
            command=self._save_question_section_preferences,
        ).pack(side="left", padx=(0, 16))
        
        tk.Checkbutton(
            section_a_sub, text="Non-Simulation", variable=self._section_a_nonsim_var,
            font=FONT_BODY, bg=C["content_bg"], fg=C["text_primary"],
            selectcolor=C["card_bg"], activebackground=C["content_bg"],
            command=self._save_question_section_preferences,
        ).pack(side="left")

        # Section B (Theory)
        self._section_b_frame = tk.Frame(parent, bg=C["content_bg"])
        self._section_b_frame.pack(fill="x", padx=40, pady=(8, 6))
        
        tk.Label(self._section_b_frame, text="Section B (Theory)", font=("Segoe UI", 10, "bold"),
                 bg=C["content_bg"], fg=C["accent"]).pack(anchor="w", pady=(0, 4))
        
        section_b_sub = tk.Frame(self._section_b_frame, bg=C["content_bg"])
        section_b_sub.pack(anchor="w", padx=(20, 0))
        
        self._section_b_sim_var = tk.BooleanVar(value=True)
        self._section_b_nonsim_var = tk.BooleanVar(value=True)
        
        tk.Checkbutton(
            section_b_sub, text="Simulation", variable=self._section_b_sim_var,
            font=FONT_BODY, bg=C["content_bg"], fg=C["text_primary"],
            selectcolor=C["card_bg"], activebackground=C["content_bg"],
            command=self._save_question_section_preferences,
        ).pack(side="left", padx=(0, 16))
        
        tk.Checkbutton(
            section_b_sub, text="Non-Simulation", variable=self._section_b_nonsim_var,
            font=FONT_BODY, bg=C["content_bg"], fg=C["text_primary"],
            selectcolor=C["card_bg"], activebackground=C["content_bg"],
            command=self._save_question_section_preferences,
        ).pack(side="left")

        # Shuffle options
        self._shuffle_frame = tk.Frame(parent, bg=C["content_bg"])
        self._shuffle_frame.pack(fill="x", padx=40, pady=(8, 6))

        self._shuffle_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            self._shuffle_frame, text="Shuffle questions", variable=self._shuffle_var,
            font=("Segoe UI", 10, "bold"), bg=C["content_bg"], fg=C["text_primary"],
            selectcolor=C["card_bg"], activebackground=C["content_bg"],
            command=self._save_question_section_preferences,
        ).pack(anchor="w")

        self._shuffle_sub = tk.Frame(self._shuffle_frame, bg=C["content_bg"])
        self._shuffle_sub.pack(anchor="w", padx=(20, 0))

        self._keep_sim_var = tk.BooleanVar(value=True)

        tk.Radiobutton(
            self._shuffle_sub, text="Keep simulation questions together",
            variable=self._keep_sim_var, value=True,
            font=FONT_BODY, bg=C["content_bg"], fg=C["text_primary"],
            selectcolor=C["card_bg"], activebackground=C["content_bg"],
            command=self._save_question_section_preferences,
        ).pack(anchor="w")

        tk.Radiobutton(
            self._shuffle_sub, text="Shuffle all questions",
            variable=self._keep_sim_var, value=False,
            font=FONT_BODY, bg=C["content_bg"], fg=C["text_primary"],
            selectcolor=C["card_bg"], activebackground=C["content_bg"],
            command=self._save_question_section_preferences,
        ).pack(anchor="w")

        self._shuffle_sub.pack_forget()  # hidden until shuffle is enabled

        self._section_status = tk.Label(parent, text="", font=FONT_LABEL,
                                         bg=C["content_bg"], fg=C["incorrect"])
        self._section_status.pack(anchor="w", padx=40, pady=(6, 0))

    def _save_question_section_preferences(self):
        a_sim = self._section_a_sim_var.get()
        a_nonsim = self._section_a_nonsim_var.get()
        b_sim = self._section_b_sim_var.get()
        b_nonsim = self._section_b_nonsim_var.get()
        
        # Block all-off state
        if not (a_sim or a_nonsim or b_sim or b_nonsim):
            self._section_a_nonsim_var.set(True)
            a_nonsim = True
            self._section_status.config(text="At least one question type must stay enabled.")
        else:
            self._section_status.config(text="")
        
        config.save_question_section_preferences(a_sim, a_nonsim, b_sim, b_nonsim)
        config.save_shuffle_preferences(self._shuffle_var.get(), self._keep_sim_var.get())
        self._set_shuffle_sub_visibility()

    def _set_shuffle_sub_visibility(self):
        if self._shuffle_var.get():
            self._shuffle_sub.pack(anchor="w", padx=(20, 0))
        else:
            self._shuffle_sub.pack_forget()

    # ── Evaluation default section ────────────────────────────────────────────
    def _build_evaluation_section(self, parent):
        tk.Label(parent, text="DEFAULT EVALUATION MODE", font=("Segoe UI", 8, "bold"),
                 bg=C["content_bg"], fg=C["text_secondary"]).pack(anchor="w", padx=40, pady=(0, 6))
        tk.Label(parent, text="ON evaluates each written answer immediately during the quiz. "
                              "OFF batches all written answers for scoring at the end.",
                 font=FONT_LABEL, bg=C["content_bg"], fg=C["text_secondary"],
                 wraplength=560, justify="left").pack(anchor="w", padx=40, pady=(0, 10))

        row = tk.Frame(parent, bg=C["content_bg"])
        row.pack(fill="x", padx=40)

        self._eval_on_btn  = self._toggle_btn_widget(row, "Evaluation ON")
        self._eval_off_btn = self._toggle_btn_widget(row, "Evaluation OFF")
        self._eval_on_btn.pack(side="left")
        self._eval_off_btn.pack(side="left", padx=(10, 0))

        self._eval_on_btn.bind("<Button-1>", lambda _: self._set_evaluation(True))
        self._eval_off_btn.bind("<Button-1>", lambda _: self._set_evaluation(False))

    def _toggle_btn_widget(self, parent, text):
        return tk.Label(parent, text=text, font=("Segoe UI", 10, "bold"),
                         bg=C["text_secondary"], fg="white", padx=16, pady=8, cursor="hand2")

    def _set_evaluation(self, on: bool):
        config.save_evaluation_on(on)
        self._eval_on_btn.config(bg=C["correct"] if on else C["text_secondary"])
        self._eval_off_btn.config(bg=C["incorrect"] if not on else C["text_secondary"])

    # ── Load saved config into UI ─────────────────────────────────────────────
    def _load_saved_config(self):
        groq_keys = config.get('groq_keys', [''] * 4)
        or_keys   = config.get('openrouter_keys', [''] * 4)
        for entry, val in zip(self._groq_entries, groq_keys + [''] * 4):
            entry.insert(0, val)
        for entry, val in zip(self._or_entries, or_keys + [''] * 4):
            entry.insert(0, val)

        groq_model = config.get('groq_model') or ''
        or_model   = config.get('openrouter_model') or ''
        self._groq_model_entry.insert(0, groq_model)
        self._or_model_entry.insert(0, or_model)

        custom_url   = config.get('custom_api_url', '')
        custom_key   = config.get('custom_api_key', '')
        custom_model = config.get('custom_model', '')
        self._custom_url_entry.insert(0, custom_url)
        self._custom_key_entry.insert(0, custom_key)
        self._custom_model_entry.insert(0, custom_model)

        cli_model = config.get_cli_model()
        self._cli_model_entry.insert(0, cli_model)

        # Apply saved provider mode
        mode = config.get_provider_mode()
        self._apply_provider_mode(mode)

        root_path = config.get_library_root()
        if root_path:
            self._root_entry.insert(0, root_path)
            self._scan_library()

        self._set_evaluation(config.get_evaluation_on())

        prefs = config.get_question_section_preferences()
        self._section_a_sim_var.set(prefs['section_a_sim'])
        self._section_a_nonsim_var.set(prefs['section_a_nonsim'])
        self._section_b_sim_var.set(prefs['section_b_sim'])
        self._section_b_nonsim_var.set(prefs['section_b_nonsim'])

        shuffle_prefs = config.get_shuffle_preferences()
        self._shuffle_var.set(shuffle_prefs['shuffle_enabled'])
        self._keep_sim_var.set(shuffle_prefs['keep_sim_together'])
        self._set_shuffle_sub_visibility()

    def on_show(self):
        pass


# ── Main window ───────────────────────────────────────────────────────────────
class MainWindow:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("StudyKit")
        self.root.geometry("1040x680")
        self.root.minsize(760, 520)
        self.root.configure(bg=C["sidebar_bg"])

        # ── Shared services ────────────────────────────────────────────────────
        if config.get_provider_mode() == 'cli_bridge':
            from ..agent_runner import AgentRunner, check_registered_agents

            self.api_client = CLIBridgeClient(model=config.get_cli_model())
            self.agent_runner = AgentRunner(self.api_client)

            missing = check_registered_agents()
            if missing:
                messagebox.showwarning(
                    "Pipeline agents not registered",
                    "These pipeline agents are missing from "
                    "~/.config/opencode/opencode.json:\n\n  • "
                    + "\n  • ".join(missing)
                    + "\n\nQuiz generation will fail until they are registered."
                )
        else:
            self.api_client = ApiClient(
                groq_keys=config.get('groq_keys', []),
                openrouter_keys=config.get('openrouter_keys', []),
                groq_model=config.get('groq_model') or None,
                openrouter_model=config.get('openrouter_model') or None,
                custom_url=config.get('custom_api_url', ''),
                custom_key=config.get('custom_api_key', ''),
                custom_model=config.get('custom_model', ''),
            )
            self.agent_runner = None
        self.evaluation_runner = EvaluationRunner(self.api_client, self.agent_runner)

        self._pages: dict[str, Page] = {}
        self._current: str | None = None

        self._build()
        self._navigate("home")

    def _build(self):
        # Lazy import to avoid circular imports (quiz_page/review_page/
        # evaluation_thread import theme.py, not main_window.py)
        from .quiz_page import QuizPage
        from .review_page import ReviewPage
        from .evaluation_thread import EvaluationThreadPage
        from .flashcards_page import FlashcardsPage

        self._sidebar = Sidebar(self.root, on_navigate=self._navigate)
        self._sidebar.pack(side="left", fill="y")
        self._sidebar.pack_propagate(False)
        self._sidebar.config(width=SIDEBAR_EXPANDED)

        self._content = tk.Frame(self.root, bg=C["content_bg"])
        self._content.pack(side="left", fill="both", expand=True)

        self._pages["home"]       = HomePage(self._content, on_navigate=self._navigate)
        self._pages["quiz"]       = QuizPage(self._content, self.root,
                                              self.api_client, self.evaluation_runner,
                                              self.agent_runner)
        self._pages["flashcards"] = FlashcardsPage(self._content)
        self._pages["review"]     = ReviewPage(self._content)
        self._pages["tutor"]      = EvaluationThreadPage(self._content, self.root,
                                                         self.evaluation_runner)
        self._pages["settings"]   = SettingsPage(self._content, self.api_client)

        # Wire references so Settings can swap the live client
        self._pages["settings"]._runner_ref = self.evaluation_runner
        self._pages["settings"]._quiz_page_ref = self._pages["quiz"]

        for page in self._pages.values():
            page.place(relx=0, rely=0, relwidth=1, relheight=1)

    def _navigate(self, page_id: str):
        if page_id not in self._pages:
            return
        if self._current:
            self._pages[self._current].lower()
        self._pages[page_id].lift()
        self._pages[page_id].on_show()
        self._current = page_id
        self._sidebar._apply_active(page_id)

    def run(self):
        self.root.mainloop()
