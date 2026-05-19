"""Minimal splash screen shown while the application initializes."""

from __future__ import annotations

import contextlib


class SplashScreen:
    """Borderless loading window shown during startup.

    Created and destroyed on the calling (main) thread to avoid the
    ``Tcl_AsyncDelete: async handler deleted by the wrong thread`` fatal
    panic that Tcl raises when its interpreter is initialised on a
    non-main thread and cleaned up from a different one.

    :meth:`close` is idempotent and safe to call multiple times.

    Example usage::

        splash = SplashScreen()
        # ... do startup work ...
        splash.close()
    """

    _BG = "#0d1117"
    _GREEN = "#3fb950"
    _TEXT = "#c9d1d9"
    _MUTED = "#8b949e"
    _BORDER = "#30363d"
    _WIDTH = 340
    _HEIGHT = 160

    def __init__(self) -> None:
        self._root = None
        try:
            import tkinter as tk
        except Exception:
            return

        try:
            root = tk.Tk()
            root.configure(bg=self._BG)
            root.title("Z7_SentinelTray")
            root.resizable(False, False)
            root.overrideredirect(True)

            w, h = self._WIDTH, self._HEIGHT
            sw = root.winfo_screenwidth()
            sh = root.winfo_screenheight()
            x = (sw - w) // 2
            y = (sh - h) // 2
            root.geometry(f"{w}x{h}+{x}+{y}")

            # 1-pixel border via outer frame
            outer = tk.Frame(root, bg=self._BORDER)
            outer.place(x=0, y=0, width=w, height=h)

            inner = tk.Frame(outer, bg=self._BG)
            inner.place(x=1, y=1, width=w - 2, height=h - 2)

            tk.Label(
                inner,
                text="Z7 SentinelTray",
                font=("Segoe UI", 16, "bold"),
                fg=self._GREEN,
                bg=self._BG,
            ).place(relx=0.5, y=52, anchor="center")

            tk.Label(
                inner,
                text="Monitor de janelas",
                font=("Segoe UI", 9),
                fg=self._MUTED,
                bg=self._BG,
            ).place(relx=0.5, y=80, anchor="center")

            tk.Label(
                inner,
                text="Iniciando...",
                font=("Segoe UI", 9),
                fg=self._TEXT,
                bg=self._BG,
            ).place(relx=0.5, y=112, anchor="center")

            root.lift()
            root.attributes("-topmost", True)
            # Render the window without entering a blocking event loop.
            root.update()
            self._root = root
        except Exception:
            with contextlib.suppress(Exception):
                if "root" in dir():
                    root.destroy()  # type: ignore[possibly-undefined]

    def close(self) -> None:
        """Destroy the splash window. Safe to call multiple times."""
        if self._root is not None:
            with contextlib.suppress(Exception):
                self._root.destroy()
            self._root = None
