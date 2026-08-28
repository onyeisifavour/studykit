"""
app.py

Thin top-level application bootstrap.

DESIGN NOTE: this was originally planned to own the full
Settings -> Chat -> Blueprint -> Load -> Quiz -> Summary orchestration.
That responsibility now lives inside ui/quiz_page.py itself, because
MainWindow wires ApiClient and EvaluationRunner directly into each page
(see ui/main_window.py). Splitting orchestration into a separate app.py
layer on top of that would just be an extra indirection with no
additional control — QuizPage already owns its full state machine.

app.py's remaining job:
  1. Construct the window (which wires all pages + shared services).
  2. Install a global Tkinter error handler so an unhandled exception in
     any callback shows a message instead of dying silently.
  3. Run the main loop.
"""

import traceback
from tkinter import messagebox

from .ui.main_window import MainWindow


class App:
    def __init__(self):
        self.window = MainWindow()
        self._install_error_handler()

    def _install_error_handler(self):
        """
        Tkinter swallows exceptions raised inside callbacks (button clicks,
        root.after() callbacks, etc.) unless report_callback_exception is
        overridden. Without this, a bug in a background API callback would
        fail silently with nothing but a traceback in a terminal the user
        may not be watching.
        """
        def _handle_tk_error(exc, val, tb):
            traceback.print_exception(exc, val, tb)
            try:
                messagebox.showerror(
                    "Unexpected error",
                    f"{val}\n\nFull details were printed to the terminal.",
                )
            except Exception:
                pass   # if even the error dialog fails, don't crash the handler

        self.window.root.report_callback_exception = _handle_tk_error

    def run(self):
        self.window.run()


def main():
    App().run()


if __name__ == '__main__':
    main()
