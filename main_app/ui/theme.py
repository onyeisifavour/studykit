"""
theme.py — Shared colour and typography tokens for all UI modules.
Extracted from main_window.py so chat_view, quiz_page, review_page, and
evaluation_thread can import styling without circular imports.
"""

C = {
    "sidebar_bg":    "#0F1B2D",
    "sidebar_hover": "#1E3A5F",
    "active_bg":     "#1E3A5F",
    "active_bar":    "#3B82F6",
    "icon_inactive": "#64748B",
    "icon_active":   "#F7F9FC",
    "label_inactive":"#64748B",
    "label_active":  "#F7F9FC",
    "content_bg":    "#F7F9FC",
    "accent":        "#F59E0B",
    "accent_blue":   "#3B82F6",
    "text_primary":  "#0F172A",
    "text_secondary":"#64748B",
    "card_bg":       "#FFFFFF",
    "border":        "#E2E8F0",
    "correct":       "#10B981",
    "incorrect":     "#EF4444",
    "flashcards":    "#8B5CF6",
    "user_bubble":   "#3B82F6",
    "ai_bubble":     "#EEF2F7",
}

FONT_BODY   = ("Segoe UI", 10)
FONT_LABEL  = ("Segoe UI", 9)
FONT_H1     = ("Segoe UI", 22, "bold")
FONT_H2     = ("Segoe UI", 16, "bold")
FONT_H3     = ("Segoe UI", 13, "bold")
FONT_MONO   = ("Consolas", 10)

SIDEBAR_EXPANDED  = 200
SIDEBAR_COLLAPSED = 58


import tkinter as tk


class Page(tk.Frame):
    """Base class for all page frames. Defined here to avoid circular imports."""
    def __init__(self, parent):
        super().__init__(parent, bg=C["content_bg"])

    def on_show(self):
        """Called each time this page becomes visible."""
        pass
