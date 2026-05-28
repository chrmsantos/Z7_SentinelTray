"""Tkinter-based GUI: main status window, config editor, and alert-recipient dialog."""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import tkinter as tk
import webbrowser
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Lock, Thread
from tkinter import messagebox

from .app import Notifier
from .config import AppConfig, get_project_root, get_user_data_dir, load_config
from .dpapi_utils import save_secret
from .status import StatusStore, format_timestamp
from .tray_app import TrayIcon, set_console_visible
from .updater import run_update_check
from .validation_utils import validate_email_address

LOGGER = logging.getLogger(__name__)
_PROJECT_REPO_URL = "https://github.com/chrmsantos/z7_sentineltray"

# ── GitHub-dark-inspired palette ─────────────────────────────────────────────
_BG = "#0d1117"  # main background
_SURFACE = "#161b22"  # header / footer surface
_CARD = "#1c2128"  # card background
_BORDER = "#30363d"  # borders
_GREEN = "#3fb950"  # primary accent (running)
_GREEN2 = "#196127"  # dark green
_RED = "#f85149"  # error / stopped
_AMBER = "#d29922"  # warning
_BLUE = "#58a6ff"  # scan button
_TEAL = "#1b5e76"  # recipients button
_TEXT = "#c9d1d9"  # primary text
_MUTED = "#8b949e"  # secondary text
_WHITE = "#e6edf3"  # bright text
_BTN_DIM = "#21262d"  # dim button bg


def _color_hover(hex_color: str) -> str:
    """Return a slightly modified version of *hex_color* for mouse-hover feedback.
    Brightens dark colors and darkens light colors.
    """
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return hex_color
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return hex_color

    # Calculate relative luminance to detect light vs dark colors
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    if luminance > 160:  # It's a light color, let's darken it for hover
        r = max(0, int(r * 0.9))
        g = max(0, int(g * 0.9))
        b = max(0, int(b * 0.9))
    else:  # It's a dark color, let's brighten it for hover
        r = min(255, r + int((255 - r) * 0.22))
        g = min(255, g + int((255 - g) * 0.22))
        b = min(255, b + int((255 - b) * 0.22))
    return f"#{r:02x}{g:02x}{b:02x}"


def _get_contrast_fg(hex_color: str) -> str:
    """Return #ffffff for dark backgrounds and #1f2328 for light backgrounds to ensure optimal contrast."""
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return "#ffffff"
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return "#ffffff"

    # Calculate relative luminance
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    return "#1f2328" if luminance > 150 else "#ffffff"



def _add_hover(btn: tk.Button, bg: str) -> None:
    """Bind a dynamic brightness/darkness-on-hover effect to *btn*."""
    btn._normal_bg = bg

    def on_enter(_e: tk.Event) -> None:
        current_bg = getattr(btn, "_normal_bg", btn.cget("bg"))
        hover = _color_hover(current_bg)
        btn.configure(bg=hover, activebackground=hover)

    def on_leave(_e: tk.Event) -> None:
        normal_bg = getattr(btn, "_normal_bg", None)
        if normal_bg:
            btn.configure(bg=normal_bg, activebackground=normal_bg)

    btn.bind("<Enter>", on_enter)
    btn.bind("<Leave>", on_leave)


# ── Theme palettes ────────────────────────────────────────────────────────────
_DARK_PALETTE: dict[str, str] = {
    "bg": _BG,
    "surface": _SURFACE,
    "card": _CARD,
    "border": _BORDER,
    "green": _GREEN,
    "green2": _GREEN2,
    "red": _RED,
    "amber": _AMBER,
    "blue": _BLUE,
    "text": _TEXT,
    "muted": _MUTED,
    "white": _WHITE,
    "btn_dim": _BTN_DIM,
    "exit_btn": "#5a1a1a",
    "select_bg": "#264f78",
    "teal": _TEAL,
}

_LIGHT_PALETTE: dict[str, str] = {
    "bg": "#ffffff",
    "surface": "#f6f8fa",
    "card": "#ffffff",
    "border": "#d0d7de",
    "green": "#1a7f37",
    "green2": "#2da44e",
    "red": "#cf222e",
    "amber": "#9a6700",
    "blue": "#0969da",
    "text": "#1f2328",
    "muted": "#656d76",
    "white": "#1f2328",
    "btn_dim": "#e6eaef",
    "exit_btn": "#ffd8d8",
    "select_bg": "#b6d3fb",
    "teal": "#d0f4f7",
}


def _apply_theme_walk(root: tk.Widget, old_pal: dict, new_pal: dict) -> None:
    """Recursively remap palette colors across all widgets."""
    color_map = {v: new_pal[k] for k, v in old_pal.items()}
    _OPTS = (  # noqa: N806
        "bg",
        "fg",
        "activebackground",
        "activeforeground",
        "insertbackground",
        "selectbackground",
    )

    def _remap(w: tk.Widget) -> None:
        normal_bg = getattr(w, "_normal_bg", None)
        if normal_bg in color_map:
            w._normal_bg = color_map[normal_bg]

        for opt in _OPTS:
            try:
                cur = w.cget(opt)
                if cur in color_map:
                    w.configure(**{opt: color_map[cur]})
            except tk.TclError:
                pass

        if isinstance(w, tk.Button):
            try:
                bg = w.cget("bg")
                fg = _get_contrast_fg(bg)
                w.configure(fg=fg, activeforeground=fg)
            except Exception:
                pass

        for child in w.winfo_children():
            _remap(child)

    _remap(root)


class _ThemeState:
    """Persisted holder for the active UI theme."""

    def __init__(self) -> None:
        self._dark = False
        self._load()

    def _pref_path(self) -> Path:
        return get_user_data_dir() / "ui_prefs.json"

    def _load(self) -> None:
        try:
            data = json.loads(self._pref_path().read_text(encoding="utf-8"))
            self._dark = bool(data.get("dark_theme", False))
        except Exception:
            self._dark = False

    def _save(self) -> None:
        try:
            p = self._pref_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({"dark_theme": self._dark}), encoding="utf-8")
        except Exception:
            pass

    @property
    def is_dark(self) -> bool:
        return self._dark

    @property
    def palette(self) -> dict:
        return _DARK_PALETTE if self._dark else _LIGHT_PALETTE

    def toggle(self, root: tk.Widget) -> None:
        old = self.palette
        self._dark = not self._dark
        self._save()
        _apply_theme_walk(root, old, self.palette)


# ─────────────────────────────────────────────────────────────────────────────
# SMTP password dialog
# ─────────────────────────────────────────────────────────────────────────────


def prompt_smtp_password_gui(username: str, monitor_index: int) -> str | None:
    """Show a modal dialog to collect the SMTP password.

    Returns the entered password, or ``None`` if the user cancelled.
    """
    result: list[str | None] = [None]

    root = tk.Tk()
    root.withdraw()

    dialog = tk.Toplevel(root)
    dialog.title("Z7_SentinelTray — Senha SMTP")
    dialog.configure(bg=_BG)
    dialog.resizable(False, False)
    dialog.grab_set()
    dialog.focus_force()

    dialog.update_idletasks()
    width, height = 380, 200
    x = (dialog.winfo_screenwidth() - width) // 2
    y = (dialog.winfo_screenheight() - height) // 2
    dialog.geometry(f"{width}x{height}+{x}+{y}")

    tk.Label(
        dialog,
        text=f"Usuário SMTP (monitor {monitor_index}):",
        bg=_BG,
        fg=_MUTED,
        font=("Segoe UI", 9),
    ).pack(pady=(18, 2))
    tk.Label(
        dialog,
        text=username,
        bg=_BG,
        fg=_WHITE,
        font=("Segoe UI", 10, "bold"),
    ).pack()
    tk.Label(
        dialog,
        text="Senha SMTP:",
        bg=_BG,
        fg=_MUTED,
        font=("Segoe UI", 9),
    ).pack(pady=(12, 2))
    entry = tk.Entry(
        dialog,
        show="*",
        bg=_SURFACE,
        fg=_TEXT,
        insertbackground=_TEXT,
        relief="flat",
        font=("Segoe UI", 10),
        width=32,
    )
    entry.pack(padx=24)
    entry.focus_set()

    def on_ok() -> None:
        result[0] = entry.get()
        dialog.destroy()

    def on_cancel() -> None:
        dialog.destroy()

    btn_frame = tk.Frame(dialog, bg=_BG)
    btn_frame.pack(pady=14)
    _ok_fg = _get_contrast_fg(_GREEN2)
    _ok_btn = tk.Button(
        btn_frame,
        text="OK",
        command=on_ok,
        bg=_GREEN2,
        fg=_ok_fg,
        activeforeground=_ok_fg,
        activebackground=_GREEN2,
        relief="flat",
        padx=20,
        font=("Segoe UI", 9),
        cursor="hand2",
    )
    _ok_btn.pack(side="left", padx=6)
    _add_hover(_ok_btn, _GREEN2)
    _cancel_fg = _get_contrast_fg(_BTN_DIM)
    _cancel_btn = tk.Button(
        btn_frame,
        text="Cancelar",
        command=on_cancel,
        bg=_BTN_DIM,
        fg=_cancel_fg,
        activeforeground=_cancel_fg,
        activebackground=_BTN_DIM,
        relief="flat",
        padx=10,
        font=("Segoe UI", 9),
        cursor="hand2",
    )
    _cancel_btn.pack(side="left", padx=6)
    _add_hover(_cancel_btn, _BTN_DIM)

    entry.bind("<Return>", lambda _e: on_ok())
    dialog.bind("<Escape>", lambda _e: on_cancel())
    dialog.protocol("WM_DELETE_WINDOW", on_cancel)

    root.wait_window(dialog)
    root.destroy()
    return result[0]


# ─────────────────────────────────────────────────────────────────────────────
# In-app YAML config editor
# ─────────────────────────────────────────────────────────────────────────────


class ConfigEditorWindow:
    """Modal-like Toplevel that lets the user edit config.local.yaml in-app."""

    def __init__(
        self,
        parent: tk.Tk,
        *,
        on_saved: Callable[[AppConfig], None],
        on_edit_recipients: Callable[[], None] | None = None,
        on_edit_smtp_credentials: Callable[[], None] | None = None,
        theme_state: _ThemeState | None = None,
    ) -> None:
        self._parent = parent
        self._on_saved = on_saved
        self._on_edit_recipients = on_edit_recipients
        self._on_edit_smtp_credentials = on_edit_smtp_credentials
        self._theme = theme_state
        self._win: tk.Toplevel | None = None
        self._text: tk.Text | None = None
        self._lineno: tk.Text | None = None
        self._status_var = tk.StringVar()
        self._status_color = tk.StringVar(value=_MUTED)
        self._status_lbl: tk.Label | None = None
        self._cfg_path = get_user_data_dir() / "config.local.yaml"

    # ── Public ────────────────────────────────────────────────────────────────

    def show(self) -> None:
        """Show the config editor window, raising it if already open."""
        if self._win is not None and self._win.winfo_exists():
            self._win.lift()
            self._win.focus_force()
            return
        self._build()
        self._load_file()

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        win = tk.Toplevel(self._parent)
        self._win = win
        win.title("Z7_SentinelTray — Editor de Configuração")
        win.configure(bg=_BG)
        win.geometry("860x620")
        win.minsize(600, 400)
        win.resizable(True, True)
        win.transient(self._parent)
        win.grab_set()

        try:
            if self._parent.iconbitmap():
                win.iconbitmap(self._parent.iconbitmap())
        except Exception:
            pass

        # ── Toolbar ───────────────────────────────────────────────────────────
        toolbar = tk.Frame(win, bg=_SURFACE, pady=8)
        toolbar.pack(fill=tk.X)
        tk.Label(
            toolbar,
            text="⚙  config.local.yaml",
            font=("Segoe UI", 10, "bold"),
            fg=_GREEN,
            bg=_SURFACE,
        ).pack(side=tk.LEFT, padx=14)
        tk.Label(
            toolbar, text=str(self._cfg_path), font=("Segoe UI", 8), fg=_MUTED, bg=_SURFACE
        ).pack(side=tk.LEFT, padx=(0, 14))
        tk.Frame(win, bg=_BORDER, height=1).pack(fill=tk.X)

        # ── Editor area ───────────────────────────────────────────────────────
        editor_frame = tk.Frame(win, bg=_BG)
        editor_frame.pack(fill=tk.BOTH, expand=True)

        # Line-number gutter
        ln = tk.Text(
            editor_frame,
            width=4,
            padx=6,
            takefocus=0,
            state="disabled",
            font=("Consolas", 11),
            bg="#0d1117",
            fg=_MUTED,
            relief=tk.FLAT,
            bd=0,
            wrap=tk.NONE,
            cursor="arrow",
        )
        ln.pack(side=tk.LEFT, fill=tk.Y)
        self._lineno = ln

        tk.Frame(editor_frame, bg=_BORDER, width=1).pack(side=tk.LEFT, fill=tk.Y)

        # Main text widget + scrollbars
        text_container = tk.Frame(editor_frame, bg=_BG)
        text_container.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        vsb = tk.Scrollbar(text_container, orient=tk.VERTICAL)
        hsb = tk.Scrollbar(text_container, orient=tk.HORIZONTAL)
        txt = tk.Text(
            text_container,
            font=("Consolas", 11),
            bg="#0d1117",
            fg=_TEXT,
            insertbackground=_GREEN,
            selectbackground="#264f78",
            relief=tk.FLAT,
            bd=0,
            wrap=tk.NONE,
            yscrollcommand=vsb.set,
            xscrollcommand=hsb.set,
            undo=True,
            tabs=("2.0c",),
        )
        vsb.config(command=self._sync_scroll)
        hsb.config(command=txt.xview)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        hsb.pack(side=tk.BOTTOM, fill=tk.X)
        txt.pack(fill=tk.BOTH, expand=True)
        self._text = txt
        self._vsb = vsb

        # Sync line numbers on key/scroll
        txt.bind("<KeyRelease>", lambda e: self._update_linenos())
        txt.bind("<MouseWheel>", lambda e: self._after_scroll())
        txt.bind("<Button-4>", lambda e: self._after_scroll())
        txt.bind("<Button-5>", lambda e: self._after_scroll())
        txt.bind("<<Modified>>", lambda e: self._on_modified())

        # ── Status bar ────────────────────────────────────────────────────────
        tk.Frame(win, bg=_BORDER, height=1).pack(fill=tk.X)
        status_bar = tk.Frame(win, bg=_SURFACE, pady=4)
        status_bar.pack(fill=tk.X)
        sl = tk.Label(
            status_bar,
            textvariable=self._status_var,
            font=("Segoe UI", 8),
            fg=_MUTED,
            bg=_SURFACE,
            anchor="w",
        )
        sl.pack(side=tk.LEFT, padx=14, fill=tk.X, expand=True)
        self._status_lbl = sl
        self._status_var.set("Pronto — Ctrl+S para salvar")

        # ── Footer buttons ────────────────────────────────────────────────────
        tk.Frame(win, bg=_BORDER, height=1).pack(fill=tk.X)
        footer = tk.Frame(win, bg=_SURFACE, pady=10)
        footer.pack(fill=tk.X)
        self._make_btn(footer, "✓  Validar", self._validate, _BTN_DIM).pack(
            side=tk.LEFT, padx=(14, 6)
        )
        self._make_btn(footer, "💾  Salvar e Aplicar", self._save_apply, _GREEN2).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        self._make_btn(
            footer, "↺  Restaurar valores padrão", self._restore_defaults, _BTN_DIM
        ).pack(side=tk.LEFT, padx=(0, 6))
        # Moved to main window for quicker access and better visibility
        if self._on_edit_smtp_credentials is not None:
            self._make_btn(
                footer, "🔑  Credenciais SMTP", self._on_edit_smtp_credentials, _AMBER
            ).pack(side=tk.LEFT, padx=(0, 6))
        self._make_btn(footer, "Cancelar", win.destroy, "#5a1a1a").pack(side=tk.RIGHT, padx=(0, 14))

        # Keyboard shortcut
        win.bind("<Control-s>", lambda e: self._save_apply())
        win.bind("<Escape>", lambda e: win.destroy())

        # Apply light theme if active
        if self._theme is not None and not self._theme.is_dark:
            _apply_theme_walk(win, _DARK_PALETTE, _LIGHT_PALETTE)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _make_btn(self, parent: tk.Frame, text: str, cmd: Callable[[], None], bg: str) -> tk.Button:
        fg = _get_contrast_fg(bg)
        btn = tk.Button(
            parent,
            text=text,
            command=cmd,
            font=("Segoe UI", 9, "bold"),
            fg=fg,
            bg=bg,
            activeforeground=fg,
            activebackground=bg,
            relief=tk.FLAT,
            cursor="hand2",
            padx=12,
            pady=5,
            bd=0,
        )
        _add_hover(btn, bg)
        return btn

    def _restore_defaults(self) -> None:
        import sys

        if not messagebox.askyesno(
            "Restaurar valores padrão",
            "Isso substituirá o conteúdo do editor pelo template padrão.\n"
            "As alterações não salvas serão perdidas. Deseja continuar?",
            parent=self._win,
        ):
            return
        meipass = getattr(sys, "_MEIPASS", None)
        candidates = []
        if meipass:
            candidates.append(Path(meipass) / "config" / "config.local.yaml.example")
        candidates.append(get_project_root() / "config" / "config.local.yaml.example")
        template_content: str | None = None
        for example_path in candidates:
            try:
                template_content = example_path.read_text(encoding="utf-8")
                break
            except Exception:
                continue
        if template_content is None:
            self._set_status("✗ Template padrão não encontrado", _RED)
            return
        if self._text:
            self._text.delete("1.0", tk.END)
            self._text.insert("1.0", template_content)
            self._text.edit_reset()
            self._text.edit_modified(False)
        self._update_linenos()
        self._set_status("Valores padrão restaurados — Ctrl+S para salvar", _AMBER)

    def _load_file(self) -> None:
        self._cfg_path.parent.mkdir(parents=True, exist_ok=True)
        if not self._cfg_path.exists():
            import sys

            meipass = getattr(sys, "_MEIPASS", None)
            candidates = []
            if meipass:
                candidates.append(Path(meipass) / "config" / "config.local.yaml.example")
            candidates.append(get_project_root() / "config" / "config.local.yaml.example")
            template_content: str | None = None
            for example_path in candidates:
                try:
                    template_content = example_path.read_text(encoding="utf-8")
                    break
                except Exception:
                    continue
            if template_content is None:
                template_content = "# Z7_SentinelTray — configuração local\n"
            self._cfg_path.write_text(template_content, encoding="utf-8")
        try:
            content = self._cfg_path.read_text(encoding="utf-8")
        except Exception as exc:
            content = f"# ERRO ao ler arquivo: {exc}\n"
        if self._text:
            self._text.delete("1.0", tk.END)
            self._text.insert("1.0", content)
            self._text.edit_reset()  # clear undo stack
            self._text.edit_modified(False)  # clear modified flag
        self._update_linenos()
        self._set_status("Arquivo carregado — Ctrl+S para salvar", _MUTED)

    def _update_linenos(self) -> None:
        txt = self._text
        ln = self._lineno
        if txt is None or ln is None:
            return
        # Determine visible line range
        first = int(txt.index("@0,0").split(".")[0])
        last_idx = txt.index(f"@0,{txt.winfo_height()}")
        last = int(last_idx.split(".")[0])
        total = int(txt.index(tk.END).split(".")[0]) - 1
        last = min(last + 1, total)
        ln.config(state="normal")
        ln.delete("1.0", tk.END)
        for i in range(first, last + 1):
            ln.insert(tk.END, f"{i}\n")
        ln.config(state="disabled")
        # Sync vertical position
        ln.yview_moveto(txt.yview()[0])

    def _sync_scroll(self, *args: object) -> None:
        if self._text:
            self._text.yview(*args)
        self._update_linenos()

    def _after_scroll(self) -> None:
        if self._win:
            self._win.after(20, self._update_linenos)

    def _on_modified(self) -> None:
        if self._text and self._text.edit_modified():
            self._set_status("Alterações não salvas — Ctrl+S para salvar", _AMBER)

    def _set_status(self, msg: str, color: str = _MUTED) -> None:
        self._status_var.set(msg)
        if self._status_lbl:
            self._status_lbl.configure(fg=color)

    def _get_content(self) -> str:
        if self._text is None:
            return ""
        return self._text.get("1.0", tk.END)

    def _validate(self) -> AppConfig | None:
        """Write to a temp path and parse; return AppConfig on success or None."""
        content = self._get_content()
        tmp = self._cfg_path.with_suffix(".yaml.validate_tmp")
        try:
            tmp.write_text(content, encoding="utf-8")
            cfg = load_config(str(tmp))
            self._set_status("✓ Configuração válida", _GREEN)
        except Exception as exc:
            self._set_status(f"✗ {exc}", _RED)
            return None
        else:
            return cfg
        finally:
            with contextlib.suppress(Exception):
                tmp.unlink(missing_ok=True)

    def _save_apply(self) -> None:
        cfg = self._validate()
        if cfg is None:
            return
        content = self._get_content()
        try:
            self._cfg_path.write_text(content, encoding="utf-8")
        except Exception as exc:
            self._set_status(f"✗ Falha ao salvar: {exc}", _RED)
            return
        if self._text:
            self._text.edit_modified(False)
        self._set_status("✓ Salvo e aplicado", _GREEN)
        self._on_saved(cfg)
        if self._win:
            self._win.after(800, self._win.destroy)


# ─────────────────────────────────────────────────────────────────────────────
# Edit to_addresses dialog
# ─────────────────────────────────────────────────────────────────────────────


class EditToAddressesDialog:
    """Modal dialog to quickly edit to_addresses for all monitors."""

    def __init__(
        self,
        parent: tk.Tk,
        *,
        cfg_path: Path,
        get_config: Callable[[], AppConfig],
        on_saved: Callable[[AppConfig], None],
        theme_state: _ThemeState | None = None,
    ) -> None:
        self._parent = parent
        self._cfg_path = cfg_path
        self._get_config = get_config
        self._on_saved = on_saved
        self._theme = theme_state
        self._win: tk.Toplevel | None = None

    def show(self) -> None:
        """Show the alert-recipient editor window, raising it if already open."""
        if self._win is not None and self._win.winfo_exists():
            self._win.lift()
            self._win.focus_force()
            return
        self._build()

    def _build(self) -> None:  # noqa: C901
        cfg = self._get_config()
        monitors = cfg.monitors

        win = tk.Toplevel(self._parent)
        self._win = win
        win.title("Z7_SentinelTray — Destinatários de Alerta")
        win.configure(bg=_BG)
        win.resizable(False, False)
        win.transient(self._parent)
        win.grab_set()
        win.focus_force()

        # Header
        header = tk.Frame(win, bg=_SURFACE, pady=10)
        header.pack(fill=tk.X)
        tk.Label(
            header,
            text="✉  Destinatários de Alerta",
            font=("Segoe UI", 11, "bold"),
            fg=_GREEN,
            bg=_SURFACE,
        ).pack(side=tk.LEFT, padx=16)
        tk.Frame(win, bg=_BORDER, height=1).pack(fill=tk.X)

        body = tk.Frame(win, bg=_BG, padx=20, pady=14)
        body.pack(fill=tk.BOTH)

        tk.Label(
            body,
            text="Informe os endereços de e-mail que receberão os alertas.\n"
            "Separe múltiplos endereços com vírgula.",
            font=("Segoe UI", 9),
            fg=_MUTED,
            bg=_BG,
            justify="left",
        ).pack(anchor="w", pady=(0, 12))

        entries: list[tk.Entry] = []
        for idx, monitor in enumerate(monitors, start=1):
            title = monitor.window_title_regex or f"Monitor {idx}"
            if len(title) > 50:
                title = title[:47] + "..."
            tk.Label(
                body,
                text=f"Monitor {idx} — {title}:",
                font=("Segoe UI", 9, "bold"),
                fg=_TEXT,
                bg=_BG,
                anchor="w",
            ).pack(anchor="w")
            current = ", ".join(monitor.email.to_addresses)
            entry = tk.Entry(
                body,
                font=("Segoe UI", 9),
                bg=_SURFACE,
                fg=_TEXT,
                insertbackground=_TEXT,
                relief="flat",
                width=56,
            )
            entry.insert(0, current)
            entry.pack(fill=tk.X, pady=(2, 10))
            entries.append(entry)

        status_var = tk.StringVar()
        status_lbl = tk.Label(
            body,
            textvariable=status_var,
            font=("Segoe UI", 8),
            fg=_RED,
            bg=_BG,
            anchor="w",
            wraplength=440,
        )
        status_lbl.pack(anchor="w", pady=(0, 4))

        tk.Frame(win, bg=_BORDER, height=1).pack(fill=tk.X)
        footer = tk.Frame(win, bg=_SURFACE, pady=10)
        footer.pack(fill=tk.X)

        def on_save() -> None:
            new_addresses: list[list[str]] = []
            for idx, entry in enumerate(entries, start=1):
                raw = entry.get().strip()
                addrs = [a.strip() for a in raw.split(",") if a.strip()]
                if not addrs:
                    status_var.set(f"✗ Monitor {idx}: informe pelo menos um endereço.")
                    status_lbl.configure(fg=_RED)
                    return
                for addr in addrs:
                    try:
                        validate_email_address(f"monitor {idx} to_addresses", addr)
                    except ValueError as exc:
                        status_var.set(f"✗ {exc}")
                        status_lbl.configure(fg=_RED)
                        return
                new_addresses.append(addrs)

            try:
                yaml_text = self._cfg_path.read_text(encoding="utf-8")
            except Exception as exc:
                status_var.set(f"✗ Falha ao ler arquivo: {exc}")
                status_lbl.configure(fg=_RED)
                return

            try:
                patched = _patch_to_addresses(yaml_text, new_addresses)
            except ValueError as exc:
                status_var.set(f"✗ {exc}")
                status_lbl.configure(fg=_RED)
                return

            tmp = self._cfg_path.with_suffix(".yaml.recipients_tmp")
            try:
                tmp.write_text(patched, encoding="utf-8")
                new_cfg = load_config(str(tmp))
            except Exception as exc:
                status_var.set(f"✗ Config inválida: {exc}")
                status_lbl.configure(fg=_RED)
                return
            finally:
                with contextlib.suppress(Exception):
                    tmp.unlink(missing_ok=True)

            try:
                self._cfg_path.write_text(patched, encoding="utf-8")
            except Exception as exc:
                status_var.set(f"✗ Falha ao salvar: {exc}")
                status_lbl.configure(fg=_RED)
                return

            self._on_saved(new_cfg)
            win.destroy()

        def on_cancel() -> None:
            win.destroy()

        _save_fg = _get_contrast_fg(_GREEN2)
        _save_btn = tk.Button(
            footer,
            text="✓  Salvar",
            command=on_save,
            font=("Segoe UI", 9, "bold"),
            fg=_save_fg,
            bg=_GREEN2,
            activeforeground=_save_fg,
            activebackground=_GREEN2,
            relief=tk.FLAT,
            cursor="hand2",
            padx=14,
            pady=6,
            bd=0,
        )
        _save_btn.pack(side=tk.LEFT, padx=(16, 6))
        _add_hover(_save_btn, _GREEN2)
        _cancel_fg = _get_contrast_fg(_BTN_DIM)
        _cancel_btn = tk.Button(
            footer,
            text="Cancelar",
            command=on_cancel,
            font=("Segoe UI", 9, "bold"),
            fg=_cancel_fg,
            bg=_BTN_DIM,
            activeforeground=_cancel_fg,
            activebackground=_BTN_DIM,
            relief=tk.FLAT,
            cursor="hand2",
            padx=14,
            pady=6,
            bd=0,
        )
        _cancel_btn.pack(side=tk.LEFT)
        _add_hover(_cancel_btn, _BTN_DIM)

        win.bind("<Escape>", lambda _e: on_cancel())
        win.protocol("WM_DELETE_WINDOW", on_cancel)

        if self._theme is not None and not self._theme.is_dark:
            _apply_theme_walk(win, _DARK_PALETTE, _LIGHT_PALETTE)

        win.update_idletasks()
        w, h = win.winfo_reqwidth(), win.winfo_reqheight()
        sx = (win.winfo_screenwidth() - w) // 2
        sy = (win.winfo_screenheight() - h) // 2
        win.geometry(f"+{sx}+{sy}")


class SmtpCredentialsDialog:
    """Modal dialog to update SMTP username and password for all monitors."""

    def __init__(
        self,
        parent: tk.Tk,
        *,
        cfg_path: Path,
        get_config: Callable[[], AppConfig],
        on_saved: Callable[[AppConfig], None],
        theme_state: _ThemeState | None = None,
    ) -> None:
        self._parent = parent
        self._cfg_path = cfg_path
        self._get_config = get_config
        self._on_saved = on_saved
        self._theme = theme_state
        self._win: tk.Toplevel | None = None

    def show(self) -> None:
        """Show the SMTP credentials editor, raising it if already open."""
        if self._win is not None and self._win.winfo_exists():
            self._win.lift()
            self._win.focus_force()
            return
        self._build()

    def _build(self) -> None:  # noqa: C901
        cfg = self._get_config()
        monitors = cfg.monitors
        # Snapshot old usernames to detect whether from_address should be auto-synced
        old_usernames = [str(m.email.smtp_username or "") for m in monitors]
        old_from_addresses = [str(m.email.from_address or "") for m in monitors]

        win = tk.Toplevel(self._parent)
        self._win = win
        win.title("Z7_SentinelTray — Credenciais SMTP")
        win.configure(bg=_BG)
        win.resizable(False, False)
        win.transient(self._parent)
        win.grab_set()
        win.focus_force()

        # Header
        header = tk.Frame(win, bg=_SURFACE, pady=10)
        header.pack(fill=tk.X)
        tk.Label(
            header,
            text="🔑  Credenciais SMTP",
            font=("Segoe UI", 11, "bold"),
            fg=_AMBER,
            bg=_SURFACE,
        ).pack(side=tk.LEFT, padx=16)
        tk.Frame(win, bg=_BORDER, height=1).pack(fill=tk.X)

        body = tk.Frame(win, bg=_BG, padx=20, pady=14)
        body.pack(fill=tk.BOTH)

        tk.Label(
            body,
            text="Informe o usuário e a senha SMTP para cada monitor.\n"
            "Deixe a senha em branco para manter a senha atual.",
            font=("Segoe UI", 9),
            fg=_MUTED,
            bg=_BG,
            justify="left",
        ).pack(anchor="w", pady=(0, 12))

        user_entries: list[tk.Entry] = []
        pass_entries: list[tk.Entry] = []

        def _make_label(parent: tk.Frame, text: str) -> None:
            tk.Label(
                parent, text=text, font=("Segoe UI", 9), fg=_MUTED, bg=_BG, width=8, anchor="w"
            ).pack(side=tk.LEFT)

        for idx, monitor in enumerate(monitors, start=1):
            title = monitor.window_title_regex or f"Monitor {idx}"
            if len(title) > 50:
                title = title[:47] + "..."
            tk.Label(
                body,
                text=f"Monitor {idx} — {title}:",
                font=("Segoe UI", 9, "bold"),
                fg=_TEXT,
                bg=_BG,
                anchor="w",
            ).pack(anchor="w")

            # Username row
            row_u = tk.Frame(body, bg=_BG)
            row_u.pack(fill=tk.X, pady=(2, 4))
            _make_label(row_u, "Usuário:")
            user_entry = tk.Entry(
                row_u,
                font=("Segoe UI", 9),
                bg=_SURFACE,
                fg=_TEXT,
                insertbackground=_TEXT,
                relief="flat",
                width=44,
            )
            user_entry.insert(0, str(monitor.email.smtp_username or ""))
            user_entry.pack(side=tk.LEFT, padx=(0, 8))
            user_entries.append(user_entry)

            # Password row with show/hide toggle
            row_p = tk.Frame(body, bg=_BG)
            row_p.pack(fill=tk.X, pady=(0, 10))
            _make_label(row_p, "Senha:")
            pass_entry = tk.Entry(
                row_p,
                show="*",
                font=("Segoe UI", 9),
                bg=_SURFACE,
                fg=_TEXT,
                insertbackground=_TEXT,
                relief="flat",
                width=38,
            )
            pass_entry.pack(side=tk.LEFT, padx=(0, 4))
            pass_entries.append(pass_entry)

            show_var = tk.BooleanVar(value=False)

            def _make_toggle(entry: tk.Entry, var: tk.BooleanVar) -> Callable[[], None]:
                def _toggle() -> None:
                    entry.config(show="" if var.get() else "*")
                return _toggle

            tk.Checkbutton(
                row_p,
                text="Mostrar",
                variable=show_var,
                command=_make_toggle(pass_entry, show_var),
                font=("Segoe UI", 8),
                bg=_BG,
                fg=_MUTED,
                activebackground=_BG,
                activeforeground=_TEXT,
                selectcolor=_SURFACE,
                relief=tk.FLAT,
                bd=0,
            ).pack(side=tk.LEFT)

        status_var = tk.StringVar()
        status_lbl = tk.Label(
            body,
            textvariable=status_var,
            font=("Segoe UI", 8),
            fg=_RED,
            bg=_BG,
            anchor="w",
            wraplength=480,
        )
        status_lbl.pack(anchor="w", pady=(0, 4))

        tk.Frame(win, bg=_BORDER, height=1).pack(fill=tk.X)
        footer = tk.Frame(win, bg=_SURFACE, pady=10)
        footer.pack(fill=tk.X)

        def on_save() -> None:
            new_usernames = [e.get().strip() for e in user_entries]
            new_passwords = [e.get() for e in pass_entries]

            for idx, username in enumerate(new_usernames, start=1):
                if not username:
                    status_var.set(f"✗ Monitor {idx}: o usuário SMTP não pode estar vazio.")
                    status_lbl.configure(fg=_RED)
                    return

            try:
                yaml_text = self._cfg_path.read_text(encoding="utf-8")
            except Exception as exc:
                status_var.set(f"✗ Falha ao ler arquivo: {exc}")
                status_lbl.configure(fg=_RED)
                return

            try:
                patched = _patch_smtp_username(yaml_text, new_usernames)
            except ValueError as exc:
                status_var.set(f"✗ {exc}")
                status_lbl.configure(fg=_RED)
                return

            # Auto-sync from_address when it previously matched smtp_username
            synced_from = [
                new_usernames[i]
                if old_from_addresses[i] == old_usernames[i] and new_usernames[i] != old_usernames[i]
                else old_from_addresses[i]
                for i in range(len(monitors))
            ]
            if synced_from != old_from_addresses:
                try:
                    patched = _patch_from_address(patched, synced_from)
                except ValueError as exc:
                    status_var.set(f"✗ {exc}")
                    status_lbl.configure(fg=_RED)
                    return

            tmp = self._cfg_path.with_suffix(".yaml.smtp_tmp")
            try:
                tmp.write_text(patched, encoding="utf-8")
                new_cfg = load_config(str(tmp))
            except Exception as exc:
                status_var.set(f"✗ Config inválida: {exc}")
                status_lbl.configure(fg=_RED)
                return
            finally:
                with contextlib.suppress(Exception):
                    tmp.unlink(missing_ok=True)

            try:
                self._cfg_path.write_text(patched, encoding="utf-8")
            except Exception as exc:
                status_var.set(f"✗ Falha ao salvar: {exc}")
                status_lbl.configure(fg=_RED)
                return

            # Persist new passwords securely via DPAPI
            for idx, password in enumerate(new_passwords, start=1):
                if not password:
                    continue
                os.environ[f"Z7_SENTINELTRAY_SMTP_PASSWORD_{idx}"] = password
                try:
                    secret_path = get_user_data_dir() / f"smtp_password_{idx}.dpapi"
                    save_secret(secret_path, password)
                except Exception as exc:
                    LOGGER.warning(
                        "Failed to store SMTP password for monitor %s: %s",
                        idx,
                        exc,
                        extra={"category": "config"},
                    )

            self._on_saved(new_cfg)
            win.destroy()

        def on_cancel() -> None:
            win.destroy()

        _save_fg = _get_contrast_fg(_GREEN2)
        _save_btn = tk.Button(
            footer,
            text="✓  Salvar",
            command=on_save,
            font=("Segoe UI", 9, "bold"),
            fg=_save_fg,
            bg=_GREEN2,
            activeforeground=_save_fg,
            activebackground=_GREEN2,
            relief=tk.FLAT,
            cursor="hand2",
            padx=14,
            pady=6,
            bd=0,
        )
        _save_btn.pack(side=tk.LEFT, padx=(16, 6))
        _add_hover(_save_btn, _GREEN2)
        _cancel_fg = _get_contrast_fg(_BTN_DIM)
        _cancel_btn = tk.Button(
            footer,
            text="Cancelar",
            command=on_cancel,
            font=("Segoe UI", 9, "bold"),
            fg=_cancel_fg,
            bg=_BTN_DIM,
            activeforeground=_cancel_fg,
            activebackground=_BTN_DIM,
            relief=tk.FLAT,
            cursor="hand2",
            padx=14,
            pady=6,
            bd=0,
        )
        _cancel_btn.pack(side=tk.LEFT)
        _add_hover(_cancel_btn, _BTN_DIM)

        win.bind("<Escape>", lambda _e: on_cancel())
        win.protocol("WM_DELETE_WINDOW", on_cancel)

        if self._theme is not None and not self._theme.is_dark:
            _apply_theme_walk(win, _DARK_PALETTE, _LIGHT_PALETTE)

        win.update_idletasks()
        w, h = win.winfo_reqwidth(), win.winfo_reqheight()
        sx = (win.winfo_screenwidth() - w) // 2
        sy = (win.winfo_screenheight() - h) // 2
        win.geometry(f"+{sx}+{sy}")


class StatusWindow:
    """Beautiful tkinter status window for Z7_SentinelTray."""

    _REFRESH_MS = 1000

    def __init__(
        self,
        root: tk.Tk,
        status: StatusStore,
        config: AppConfig,
        *,
        get_config: Callable[[], AppConfig],
        on_manual_scan: Callable[[], None],
        on_open_config: Callable[[], None],
        on_exit: Callable[[], None],
        theme_state: _ThemeState | None = None,
        pause_event: Event | None = None,
        on_edit_recipients: Callable[[], None] | None = None,
    ) -> None:
        self._root = root
        self._status = status
        self._get_config = get_config
        self._on_manual_scan = on_manual_scan
        self._on_open_config = on_open_config
        self._on_exit = on_exit
        self._theme = theme_state or _ThemeState()
        self._pause_event = pause_event
        self._on_edit_recipients = on_edit_recipients
        self._pause_btn: tk.Button | None = None
        self._visible = False
        self._after_id: str | None = None
        self._vars: dict[str, tk.StringVar] = {}
        self._value_labels: dict[str, tk.Label] = {}
        self._monitors_content: tk.Frame | None = None
        self._status_dot: tk.Label | None = None
        self._status_text: tk.Label | None = None
        self._theme_btn: tk.Button | None = None
        self._uptime_var = tk.StringVar(value="00:00:00")
        self._pulse_id: str | None = None
        self._pulse_state: bool = True

        # Initial active windows capture
        import sys
        if sys.platform == "win32":
            try:
                import ctypes
                user32 = ctypes.windll.user32
                active_titles = []
                @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
                def enum_proc(hwnd, lParam) -> bool:
                    if user32.IsWindowVisible(hwnd):
                        length = user32.GetWindowTextLengthW(hwnd)
                        if length > 0:
                            buf = ctypes.create_unicode_buffer(length + 1)
                            user32.GetWindowTextW(hwnd, buf, length + 1)
                            title = buf.value
                            if title and title != "Program Manager":
                                active_titles.append(title)
                    return True
                user32.EnumWindows(enum_proc, 0)
                self._status.set_active_windows(active_titles)
            except Exception:
                pass
        else:
            self._status.set_active_windows(["Mock Window A", "Mock Window B"])

        self._build_ui()
        if not self._theme.is_dark:
            _apply_theme_walk(self._root, _DARK_PALETTE, _LIGHT_PALETTE)

    # ── UI Construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        r = self._root
        from . import __release_date__, __version_label__

        r.title(f"Z7_SentinelTray {__version_label__} ({__release_date__}) — Status")
        r.configure(bg=_BG)
        r.resizable(True, True)
        r.minsize(900, 480)
        r.protocol("WM_DELETE_WINDOW", self.hide)
        r.withdraw()

        # App icon
        try:
            from .path_utils import get_project_root as _gpr  # type: ignore[attr-defined]

            ico = _gpr() / "assets" / "icon.ico"
            if ico.exists():
                r.iconbitmap(str(ico))
        except Exception:
            pass

        W, H = 1080, 580  # noqa: N806
        self._center(W, H)
        r.geometry(f"{W}x{H}")

        # ── Header ────────────────────────────────────────────────────────────
        header = tk.Frame(r, bg=_SURFACE, pady=14)
        header.pack(fill=tk.X)

        eye = tk.Canvas(header, width=42, height=42, bg=_SURFACE, highlightthickness=0)
        eye.pack(side=tk.LEFT, padx=(18, 10))
        self._draw_eye(eye, 42)

        title_frame = tk.Frame(header, bg=_SURFACE)
        title_frame.pack(side=tk.LEFT)
        tk.Label(
            title_frame,
            text="Z7_SentinelTray",
            font=("Segoe UI", 15, "bold"),
            fg=_GREEN,
            bg=_SURFACE,
            anchor="w",
        ).pack(anchor="w")
        tk.Label(
            title_frame,
            text="Monitor de Janelas e Alertas",
            font=("Segoe UI", 9),
            fg=_MUTED,
            bg=_SURFACE,
            anchor="w",
        ).pack(anchor="w")

        tk.Label(
            header,
            text=f"v{__version_label__}  ·  {__release_date__}",
            font=("Segoe UI", 8),
            fg=_MUTED,
            bg=_SURFACE,
        ).pack(side=tk.RIGHT, padx=18)

        tk.Frame(r, bg=_BORDER, height=1).pack(fill=tk.X)

        # ── Footer ────────────────────────────────────────────────────────────
        footer_sep = tk.Frame(r, bg=_BORDER, height=1)
        footer_sep.pack(side=tk.BOTTOM, fill=tk.X)
        footer = tk.Frame(r, bg=_SURFACE, pady=8)
        footer.pack(side=tk.BOTTOM, fill=tk.X)

        # Upper row: Buttons
        btn_row = tk.Frame(footer, bg=_SURFACE)
        btn_row.pack(fill=tk.X, padx=18, pady=(2, 4))

        self._make_btn(btn_row, "⟳  Verificar Agora", self._trigger_scan, _BLUE).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        self._pause_btn = self._make_btn(btn_row, "⏸  Pausar", self._toggle_pause, _AMBER)
        self._pause_btn.pack(side=tk.LEFT, padx=(0, 6))
        if self._on_edit_recipients is not None:
            self._make_btn(btn_row, "✉  Destinatários", self._on_edit_recipients, _TEAL).pack(
                side=tk.LEFT, padx=(0, 6)
            )
        self._make_btn(btn_row, "⚙  Avançado", self._on_open_config, _BTN_DIM).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        self._make_btn(
            btn_row, "↗  Repositório", lambda: webbrowser.open(_PROJECT_REPO_URL), _BTN_DIM
        ).pack(side=tk.LEFT, padx=(0, 6))
        theme_label = "☀  Tema Claro" if self._theme.is_dark else "🌙  Tema Escuro"
        self._theme_btn = self._make_btn(btn_row, theme_label, self._toggle_theme, _BTN_DIM)
        self._theme_btn.pack(side=tk.LEFT, padx=(0, 6))
        self._make_btn(btn_row, "🚀  Atualizar", self._trigger_update, _GREEN).pack(
            side=tk.LEFT
        )

        self._make_btn(btn_row, "Sair  ✕", self._on_exit, "#5a1a1a").pack(
            side=tk.RIGHT
        )

        # Lower row: Copyright and motto text
        text_row = tk.Frame(footer, bg=_SURFACE)
        text_row.pack(fill=tk.X, padx=18, pady=(2, 2))

        tk.Label(
            text_row,
            text=(
                "Z7_SentinelTray • Licenced under GPLv3"
                " •  Câmara Municipal de Santa Bárbara d'Oeste/SP"
                "  • CMS"
            ),
            font=("Segoe UI", 8),
            fg=_MUTED,
            bg=_SURFACE,
        ).pack(side=tk.LEFT)

        tk.Label(
            text_row,
            text="Dharma, virtude e gratidão.",
            font=("Segoe UI", 8, "italic"),
            fg=_MUTED,
            bg=_SURFACE,
        ).pack(side=tk.RIGHT)

        # ── Two-column body ───────────────────────────────────────────────────
        body_outer = tk.Frame(r, bg=_BG)
        body_outer.pack(fill=tk.BOTH, expand=True, padx=16, pady=12)
        body_outer.columnconfigure(0, weight=1)
        body_outer.columnconfigure(1, weight=1)
        body_outer.rowconfigure(0, weight=1)

        left = tk.Frame(body_outer, bg=_BG)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        right = tk.Frame(body_outer, bg=_BG)
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))

        # ── LEFT: Status + Uptime row ─────────────────────────────────────────
        row1 = tk.Frame(left, bg=_BG)
        row1.pack(fill=tk.X, pady=(0, 10))

        sc, sc_c = self._make_card(row1, "STATUS")
        sc.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6))
        pill = tk.Frame(sc_c, bg=_CARD)
        pill.pack(pady=6)
        self._status_dot = tk.Label(pill, text="●", font=("Segoe UI", 22), fg=_AMBER, bg=_CARD)
        self._status_dot.pack(side=tk.LEFT)
        self._status_text = tk.Label(
            pill, text="INICIANDO", font=("Segoe UI", 14, "bold"), fg=_AMBER, bg=_CARD
        )
        self._status_text.pack(side=tk.LEFT, padx=(8, 0))

        uc, uc_c = self._make_card(row1, "⏱  TEMPO ATIVO")
        uc.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(6, 0))
        tk.Label(
            uc_c, textvariable=self._uptime_var, font=("Consolas", 20, "bold"), fg=_TEXT, bg=_CARD
        ).pack(pady=6)

        # ── LEFT: Scan Status ─────────────────────────────────────────────────
        self._kv_section(
            left,
            "🔍  VERIFICAÇÃO",
            [
                ("last_scan", "Última Verificação"),
                ("next_scan", "Próxima Verificação"),
                ("last_result", "Último Resultado"),
            ],
        )

        # ── LEFT: Alerts ──────────────────────────────────────────────────────
        self._kv_section(
            left,
            "🔔  ALERTAS",
            [
                ("last_match", "Última Detecção"),
                ("last_match_at", "Horário da Detecção"),
                ("last_send", "Último Alerta Enviado"),
            ],
        )

        # ── LEFT: Active Windows ──────────────────────────────────────────────
        win_outer, win_c = self._make_card(left, "🪟  JANELAS ATIVAS")
        win_outer.pack(fill=tk.BOTH, expand=True, pady=(10, 0))

        # Scrollable container using Canvas and Scrollbar
        win_container = tk.Frame(win_c, bg=_CARD)
        win_container.pack(fill=tk.BOTH, expand=True)

        self._win_canvas = tk.Canvas(win_container, bg=_CARD, highlightthickness=0)
        win_scrollbar = tk.Scrollbar(win_container, orient=tk.VERTICAL, command=self._win_canvas.yview)
        self._win_scrollable = tk.Frame(self._win_canvas, bg=_CARD)

        self._win_scrollable.bind(
            "<Configure>",
            lambda e: self._win_canvas.configure(
                scrollregion=self._win_canvas.bbox("all")
            )
        )

        self._win_canvas_window = self._win_canvas.create_window((0, 0), window=self._win_scrollable, anchor="nw")

        self._win_canvas.bind(
            "<Configure>",
            lambda e: self._win_canvas.itemconfigure(self._win_canvas_window, width=e.width)
        )

        self._win_canvas.configure(yscrollcommand=win_scrollbar.set)
        self._win_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        win_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        def _on_mousewheel(event) -> None:
            self._win_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        self._win_canvas.bind("<MouseWheel>", _on_mousewheel)
        self._win_scrollable.bind("<MouseWheel>", _on_mousewheel)

        # ── RIGHT: Errors ─────────────────────────────────────────────────────
        self._kv_section(
            right,
            "⚠  ERROS",
            [
                ("error_count", "Total de Erros"),
                ("last_error", "Último Erro"),
                ("breaker_active", "Disjuntores"),
            ],
        )

        # ── RIGHT: Email Queue ────────────────────────────────────────────────
        eq_outer, eq_c = self._make_card(right, "📧  FILA DE E-MAIL")
        eq_outer.pack(fill=tk.X, pady=(10, 0))
        for key, label, color in (
            ("q_pending", "Pendente", _AMBER),
            ("q_sent", "Enviado", _GREEN),
            ("q_failed", "Falhou", _RED),
            ("q_deferred", "Adiado", _MUTED),
        ):
            cell = tk.Frame(eq_c, bg=_CARD)
            cell.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=4)
            var = tk.StringVar(value="0")
            self._vars[key] = var
            tk.Label(
                cell, textvariable=var, font=("Consolas", 22, "bold"), fg=color, bg=_CARD
            ).pack()
            tk.Label(cell, text=label, font=("Segoe UI", 8), fg=_MUTED, bg=_CARD).pack()

        # ── RIGHT: Monitors ───────────────────────────────────────────────────
        mon_outer, mon_c = self._make_card(right, "👁  MONITORES")
        mon_outer.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        self._monitors_content = mon_c

    def _make_card(self, parent: tk.Widget, title: str) -> tuple[tk.Frame, tk.Frame]:
        """Create a styled card. Returns (outer, content). Caller packs outer."""
        outer = tk.Frame(parent, bg=_BORDER, padx=1, pady=1)
        inner = tk.Frame(outer, bg=_CARD)
        inner.pack(fill=tk.BOTH, expand=True)
        header_row = tk.Frame(inner, bg=_SURFACE)
        header_row.pack(fill=tk.X)
        tk.Label(
            header_row, text=title, font=("Segoe UI", 8, "bold"), fg=_GREEN, bg=_SURFACE, anchor="w"
        ).pack(fill=tk.X, padx=10, pady=(6, 5))
        tk.Frame(inner, bg=_BORDER, height=1).pack(fill=tk.X)
        content = tk.Frame(inner, bg=_CARD)
        content.pack(fill=tk.BOTH, expand=True, padx=12, pady=(6, 10))
        return outer, content

    def _kv_section(
        self,
        parent: tk.Widget,
        title: str,
        rows: list[tuple[str, str]],
    ) -> None:
        outer, content = self._make_card(parent, title)
        outer.pack(fill=tk.X, pady=(10, 0))
        for key, label in rows:
            var = tk.StringVar(value="—")
            self._vars[key] = var
            row = tk.Frame(content, bg=_CARD)
            row.pack(fill=tk.X, pady=1)
            tk.Label(
                row,
                text=label + ":",
                font=("Segoe UI", 9),
                fg=_MUTED,
                bg=_CARD,
                width=20,
                anchor="w",
            ).pack(side=tk.LEFT)
            lbl = tk.Label(
                row,
                textvariable=var,
                font=("Segoe UI", 9),
                fg=_TEXT,
                bg=_CARD,
                anchor="w",
                wraplength=320,
                justify="left",
            )
            lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)
            self._value_labels[key] = lbl

    def _make_btn(self, parent: tk.Frame, text: str, cmd: Callable[[], None], bg: str) -> tk.Button:
        fg = _get_contrast_fg(bg)
        btn = tk.Button(
            parent,
            text=text,
            command=cmd,
            font=("Segoe UI", 9, "bold"),
            fg=fg,
            bg=bg,
            activeforeground=fg,
            activebackground=bg,
            relief=tk.FLAT,
            cursor="hand2",
            padx=14,
            pady=6,
            bd=0,
        )
        _add_hover(btn, bg)
        return btn

    # ── Pulse animation ───────────────────────────────────────────────────────

    def _start_pulse(self) -> None:
        if self._pulse_id is None:
            self._pulse_state = True
            self._do_pulse()

    def _stop_pulse(self) -> None:
        if self._pulse_id:
            with contextlib.suppress(Exception):
                self._root.after_cancel(self._pulse_id)
            self._pulse_id = None

    def _do_pulse(self) -> None:
        self._pulse_id = None
        if self._status_dot is None:
            return
        p = self._theme.palette
        self._status_dot.configure(fg=p["green"] if self._pulse_state else p["green2"])
        self._pulse_state = not self._pulse_state
        self._pulse_id = self._root.after(600, self._do_pulse)

    def _draw_eye(self, canvas: tk.Canvas, size: int) -> None:
        cx, cy = size // 2, size // 2
        ew, eh = int(size * 0.90), int(size * 0.54)
        ex0, ey0 = cx - ew // 2, cy - eh // 2
        ex1, ey1 = ex0 + ew, ey0 + eh
        canvas.create_oval(ex0, ey0, ex1, ey1, fill="white", outline="#0a4a0a", width=2)
        r = int(size * 0.20)
        canvas.create_oval(cx - r, cy - r, cx + r, cy + r, fill="#196127")
        r = int(size * 0.14)
        canvas.create_oval(cx - r, cy - r, cx + r, cy + r, fill="#3fb950")
        r = int(size * 0.09)
        canvas.create_oval(cx - r, cy - r, cx + r, cy + r, fill="#0a0a0a")
        hl = int(size * 0.04)
        hx, hy = cx + int(size * 0.07), cy - int(size * 0.07)
        canvas.create_oval(hx - hl, hy - hl, hx + hl, hy + hl, fill="white")

    def _center(self, w: int, h: int) -> None:
        sw = self._root.winfo_screenwidth()
        sh = self._root.winfo_screenheight()
        self._root.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")

    # ── Visibility ────────────────────────────────────────────────────────────

    def show(self) -> None:
        """Make the main window visible and schedule the refresh loop."""
        self._visible = True
        self._root.deiconify()
        self._root.state("zoomed")
        self._root.lift()
        self._root.focus_force()
        self._schedule_refresh()

    def hide(self) -> None:
        """Hide the main window and cancel any pending refresh."""
        self._visible = False
        self._root.withdraw()
        if self._after_id:
            with contextlib.suppress(Exception):
                self._root.after_cancel(self._after_id)
            self._after_id = None
        self._stop_pulse()

    # ── Refresh loop ──────────────────────────────────────────────────────────

    def _schedule_refresh(self) -> None:
        if self._after_id:
            with contextlib.suppress(Exception):
                self._root.after_cancel(self._after_id)
        self._after_id = self._root.after(self._REFRESH_MS, self._refresh)

    def _refresh(self) -> None:
        self._after_id = None
        try:
            self._update_ui()
        except Exception as exc:
            LOGGER.debug("GUI refresh error: %s", exc)
        if self._visible:
            self._schedule_refresh()

    def _update_ui(self) -> None:
        snap = self._status.snapshot()
        cfg = self._get_config()

        # ── Status indicator ──────────────────────────────────────────────────
        if self._status_dot is None or self._status_text is None:
            return
        if snap.paused:
            self._stop_pulse()
            self._status_dot.configure(fg=self._theme.palette["amber"])
            self._status_text.configure(text="PAUSADO", fg=self._theme.palette["amber"])
        elif snap.running:
            self._start_pulse()
            self._status_text.configure(text="EXECUTANDO", fg=self._theme.palette["green"])
        else:
            self._stop_pulse()
            self._status_dot.configure(fg=self._theme.palette["red"])
            self._status_text.configure(text="PARADO", fg=self._theme.palette["red"])

        # ── Pause button state ────────────────────────────────────────────────
        if self._pause_btn is not None and self._pause_event is not None:
            p = self._theme.palette
            if self._pause_event.is_set():
                btn_text = "▶  Continuar"
                btn_bg = p["green"]
            else:
                btn_text = "⏸  Pausar"
                btn_bg = p["amber"]
            fg = _get_contrast_fg(btn_bg)
            self._pause_btn.configure(
                text=btn_text,
                bg=btn_bg,
                fg=fg,
                activeforeground=fg,
                activebackground=btn_bg,
            )
            _add_hover(self._pause_btn, btn_bg)

        # ── Uptime ────────────────────────────────────────────────────────────
        if snap.started_at is not None:
            elapsed = int((datetime.now(UTC) - snap.started_at).total_seconds())
        else:
            elapsed = snap.uptime_seconds
        h, rem = divmod(max(0, elapsed), 3600)
        m, s = divmod(rem, 60)
        self._uptime_var.set(f"{h:02d}:{m:02d}:{s:02d}")

        # ── Scan ──────────────────────────────────────────────────────────────
        self._set("last_scan", format_timestamp(snap.last_scan) or "—")
        self._set("next_scan", _fmt_next_scan(snap.last_scan, cfg.poll_interval_seconds))
        self._set("last_result", snap.last_scan_result or "—")

        # ── Alerts ────────────────────────────────────────────────────────────
        self._set("last_match", snap.last_match or "—")
        self._set("last_match_at", format_timestamp(snap.last_match_at) or "—")
        last_send_fmt = format_timestamp(snap.last_send)
        self._set("last_send", last_send_fmt or "—")

        # ── Errors ────────────────────────────────────────────────────────────
        self._set("error_count", str(snap.error_count))
        lbl = self._value_labels.get("error_count")
        if lbl:
            lbl.configure(
                fg=self._theme.palette["red"] if snap.error_count else self._theme.palette["green"]
            )

        self._set("last_error", snap.last_error or "—")
        lbl = self._value_labels.get("last_error")
        if lbl:
            lbl.configure(
                fg=self._theme.palette["red"] if snap.last_error else self._theme.palette["muted"]
            )

        self._set("breaker_active", str(snap.breaker_active_count))
        lbl = self._value_labels.get("breaker_active")
        if lbl:
            lbl.configure(
                fg=self._theme.palette["red"]
                if snap.breaker_active_count
                else self._theme.palette["text"]
            )

        # ── Email queue ───────────────────────────────────────────────────────
        q = snap.email_queue
        self._set("q_pending", str(q.get("queued", 0)))
        self._set("q_sent", str(q.get("sent", 0)))
        self._set("q_failed", str(q.get("failed", 0)))
        self._set("q_deferred", str(q.get("deferred", 0)))

        # ── Monitors ──────────────────────────────────────────────────────────
        self._update_monitors(snap, cfg)

        # ── Active Windows ────────────────────────────────────────────────────
        self._update_active_windows(snap)

    def _set(self, key: str, value: str) -> None:
        var = self._vars.get(key)
        if var is not None:
            var.set(value)

    def _update_monitors(self, snap: object, cfg: AppConfig) -> None:
        if self._monitors_content is None:
            return
        for w in self._monitors_content.winfo_children():
            w.destroy()
        if not cfg.monitors:
            p = self._theme.palette
            tk.Label(
                self._monitors_content,
                text="Nenhum monitor configurado.",
                font=("Segoe UI", 9),
                fg=p["muted"],
                bg=p["card"],
            ).pack(anchor="w")
            return
        failures = getattr(snap, "monitor_failures", {})
        breakers = getattr(snap, "monitor_breakers_active", {})
        p = self._theme.palette
        for idx, monitor in enumerate(cfg.monitors, start=1):
            key = monitor.window_title_regex or f"monitor_{idx}"
            fail_count = failures.get(key, 0)
            breaker = breakers.get(key, False)
            if breaker:
                dot_fg, note = p["red"], "  [CIRCUITO ABERTO]"
            elif fail_count > 0:
                dot_fg, note = p["amber"], f"  {fail_count} falha(s)"
            else:
                dot_fg, note = p["green"], ""
            row = tk.Frame(self._monitors_content, bg=p["card"])
            row.pack(fill=tk.X, pady=2)
            tk.Label(row, text="●", font=("Segoe UI", 11), fg=dot_fg, bg=p["card"]).pack(
                side=tk.LEFT, padx=(0, 8)
            )
            title = monitor.window_title_regex or f"Monitor {idx}"
            if len(title) > 48:
                title = title[:45] + "..."
            tk.Label(
                row,
                text=f"Monitor {idx}:  {title}",
                font=("Segoe UI", 9),
                fg=p["text"],
                bg=p["card"],
            ).pack(side=tk.LEFT)
            if note:
                tk.Label(
                    row,
                    text=note,
                    font=("Segoe UI", 9),
                    fg=p["red"] if breaker else p["amber"],
                    bg=p["card"],
                ).pack(side=tk.LEFT)

    def _update_active_windows(self, snap: object) -> None:
        if not hasattr(self, "_win_scrollable") or self._win_scrollable is None:
            return
        for w in self._win_scrollable.winfo_children():
            w.destroy()

        p = self._theme.palette
        active_windows = getattr(snap, "active_windows", [])
        if not active_windows:
            lbl = tk.Label(
                self._win_scrollable,
                text="Nenhuma janela detectada.",
                font=("Segoe UI", 9),
                fg=p["muted"],
                bg=p["card"],
                anchor="w",
            )
            lbl.pack(fill=tk.X, pady=2, padx=4)

            def _on_scroll(event) -> None:
                self._win_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            lbl.bind("<MouseWheel>", _on_scroll)
            return

        def _on_scroll(event) -> None:
            self._win_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        for _idx, title in enumerate(active_windows, start=1):
            row = tk.Frame(self._win_scrollable, bg=p["card"])
            row.pack(fill=tk.X, pady=1)
            row.bind("<MouseWheel>", _on_scroll)

            dot = tk.Label(row, text="•", font=("Segoe UI", 10), fg=p["teal"], bg=p["card"])
            dot.pack(side=tk.LEFT, padx=(4, 6))
            dot.bind("<MouseWheel>", _on_scroll)

            display_title = title
            if len(display_title) > 60:
                display_title = display_title[:57] + "..."

            lbl = tk.Label(
                row,
                text=display_title,
                font=("Segoe UI", 9),
                fg=p["text"],
                bg=p["card"],
                anchor="w",
                justify=tk.LEFT,
            )
            lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)
            lbl.bind("<MouseWheel>", _on_scroll)

    def _trigger_scan(self) -> None:
        self._on_manual_scan()

    def _toggle_pause(self) -> None:
        if self._pause_event is None:
            return
        if self._pause_event.is_set():
            self._pause_event.clear()
        else:
            self._pause_event.set()
        self._update_ui()

    def _toggle_theme(self) -> None:
        self._theme.toggle(self._root)
        if self._theme_btn is not None:
            p = self._theme.palette
            label = "☀  Tema Claro" if self._theme.is_dark else "🌙  Tema Escuro"
            self._theme_btn.configure(
                text=label,
                bg=p["btn_dim"],
                fg=p["white"],
                activebackground=p["btn_dim"],
                activeforeground=p["white"],
            )

    def _trigger_update(self) -> None:
        from . import __version__
        run_update_check(self._root, self._theme, __version__)


# ── Module-level helpers ──────────────────────────────────────────────────────


def _patch_to_addresses(yaml_text: str, addresses_per_monitor: list[list[str]]) -> str:
    """Replace each to_addresses line in *yaml_text* with the given address lists.

    Preserves all other content (comments, keys, order). Raises ValueError if the
    number of to_addresses fields in the file differs from *addresses_per_monitor*.
    """
    pattern = re.compile(r"^( *to_addresses:)[ \t].*$", re.MULTILINE)
    matches = list(pattern.finditer(yaml_text))
    if len(matches) != len(addresses_per_monitor):
        raise ValueError(
            f"Número de campos to_addresses no arquivo ({len(matches)}) "
            f"difere do número de monitores ({len(addresses_per_monitor)}). "
            "Use o editor de configuração completo."
        )
    result = yaml_text
    for match, new_addrs in zip(reversed(matches), reversed(addresses_per_monitor), strict=False):
        indent = match.group(1)  # e.g. "    to_addresses:"
        addrs_yaml = "[" + ", ".join(f"'{a}'" for a in new_addrs) + "]"
        new_line = f"{indent} {addrs_yaml}"
        result = result[: match.start()] + new_line + result[match.end() :]
    return result


def _patch_smtp_username(yaml_text: str, usernames_per_monitor: list[str]) -> str:
    """Replace each smtp_username line in *yaml_text* with the given values.

    Preserves all other content (comments, keys, order). Raises ValueError if the
    number of smtp_username fields in the file differs from *usernames_per_monitor*.
    """
    pattern = re.compile(r"^( *smtp_username:)[ \t].*$", re.MULTILINE)
    matches = list(pattern.finditer(yaml_text))
    if len(matches) != len(usernames_per_monitor):
        raise ValueError(
            f"Número de campos smtp_username no arquivo ({len(matches)}) "
            f"difere do número de monitores ({len(usernames_per_monitor)}). "
            "Use o editor de configuração completo."
        )
    result = yaml_text
    for match, new_user in zip(reversed(matches), reversed(usernames_per_monitor), strict=False):
        indent = match.group(1)  # e.g. "    smtp_username:"
        new_line = f"{indent} '{new_user}'"
        result = result[: match.start()] + new_line + result[match.end() :]
    return result


def _patch_from_address(yaml_text: str, addresses_per_monitor: list[str]) -> str:
    """Replace each from_address line in *yaml_text* with the given values.

    Preserves all other content (comments, keys, order). Raises ValueError if the
    number of from_address fields in the file differs from *addresses_per_monitor*.
    """
    pattern = re.compile(r"^( *from_address:)[ \t].*$", re.MULTILINE)
    matches = list(pattern.finditer(yaml_text))
    if len(matches) != len(addresses_per_monitor):
        raise ValueError(
            f"Número de campos from_address no arquivo ({len(matches)}) "
            f"difere do número de monitores ({len(addresses_per_monitor)}). "
            "Use o editor de configuração completo."
        )
    result = yaml_text
    for match, new_addr in zip(reversed(matches), reversed(addresses_per_monitor), strict=False):
        indent = match.group(1)
        new_line = f"{indent} '{new_addr}'"
        result = result[: match.start()] + new_line + result[match.end() :]
    return result


def _fmt_next_scan(last_scan: str, poll_interval_seconds: int) -> str:
    if not last_scan or not poll_interval_seconds:
        return "—"
    try:
        last = datetime.fromisoformat(last_scan)
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        remaining = (
            last + timedelta(seconds=poll_interval_seconds) - datetime.now(UTC)
        ).total_seconds()
    except (ValueError, TypeError):
        return "—"
    else:
        if remaining <= 0:
            return "iminente"
        m, s = divmod(int(remaining), 60)
        return f"em {m}m {s:02d}s" if m else f"em {s}s"


class _NotifierHandle:
    """Thread-safe composite holder for the active notifier's lifecycle state.

    A :class:`threading.Lock` ensures that :meth:`is_dead` and :meth:`replace`
    are atomic with respect to each other, guarding against the TOCTOU window
    where the watchdog thread could observe a dead thread paired with an unset
    stop event just as ``_reload_notifier`` is swapping in a fresh notifier.
    """

    def __init__(self, *, stop: Event, thread: Thread, config: AppConfig) -> None:
        self._lock = Lock()
        self.stop = stop
        self.thread = thread
        self.config = config

    def replace(
        self,
        *,
        new_stop: Event,
        new_thread: Thread,
        new_config: AppConfig,
    ) -> None:
        """Atomically swap all three fields.

        Assigns ``thread`` before ``stop`` so the watchdog never observes the
        contradictory state of a dead thread paired with an unset stop event.
        """
        with self._lock:
            self.thread = new_thread  # live thread first — watchdog short-circuits on is_alive
            self.stop = new_stop
            self.config = new_config

    def is_dead(self) -> bool:
        """Return True only if the thread exited and its stop event is not set."""
        with self._lock:
            return not self.thread.is_alive() and not self.stop.is_set()


def _start_notifier(
    config: AppConfig,
    status: StatusStore,
    stop_event: Event,
    manual_scan_event: Event,
    scan_complete_event: Event | None = None,
    test_message_event: Event | None = None,
    pause_event: Event | None = None,
) -> Thread:
    notifier = Notifier(config=config, status=status)
    t = Thread(
        target=notifier.run_loop,
        args=(stop_event, manual_scan_event, scan_complete_event, test_message_event, pause_event),
        daemon=False,
        name="monitor-loop",
    )
    t.start()
    return t


# ── Main entry point ──────────────────────────────────────────────────────────


def run_gui(config: AppConfig, *, smtp_validator: object = None) -> None:
    """GUI entry point — opens the status window on startup."""
    set_console_visible(False)

    status = StatusStore()
    manual_scan_event = Event()
    scan_complete_event = Event()
    test_message_event = Event()
    exit_event = Event()
    pause_event = Event()

    _initial_stop = Event()
    _initial_thread = _start_notifier(
        config,
        status,
        _initial_stop,
        manual_scan_event,
        scan_complete_event,
        test_message_event,
        pause_event,
    )
    handle = _NotifierHandle(
        stop=_initial_stop,
        thread=_initial_thread,
        config=config,
    )

    # ── Tk root ───────────────────────────────────────────────────────────────
    root = tk.Tk()
    root.withdraw()

    # ── Theme state ───────────────────────────────────────────────────────────
    theme = _ThemeState()

    # ── Config editor ─────────────────────────────────────────────────────────
    def _reload_notifier(new_cfg: AppConfig) -> None:
        handle.stop.set()
        with contextlib.suppress(Exception):
            handle.thread.join(timeout=5)
        new_stop = Event()
        # Clear shared events so the new notifier starts with a clean state.
        manual_scan_event.clear()
        scan_complete_event.clear()
        test_message_event.clear()
        status.set_last_error("")
        new_thread = _start_notifier(
            new_cfg,
            status,
            new_stop,
            manual_scan_event,
            scan_complete_event,
            test_message_event,
            pause_event,
        )
        handle.replace(new_stop=new_stop, new_thread=new_thread, new_config=new_cfg)

    cfg_path = get_user_data_dir() / "config.local.yaml"
    recipients_editor = EditToAddressesDialog(
        root,
        cfg_path=cfg_path,
        get_config=lambda: handle.config,
        on_saved=_reload_notifier,
        theme_state=theme,
    )

    def open_recipients() -> None:
        root.after(0, recipients_editor.show)

    smtp_credentials_dialog = SmtpCredentialsDialog(
        root,
        cfg_path=cfg_path,
        get_config=lambda: handle.config,
        on_saved=_reload_notifier,
        theme_state=theme,
    )

    def open_smtp_credentials() -> None:
        root.after(0, smtp_credentials_dialog.show)

    editor = ConfigEditorWindow(
        root,
        on_saved=_reload_notifier,
        on_edit_recipients=open_recipients,
        on_edit_smtp_credentials=open_smtp_credentials,
        theme_state=theme,
    )

    def open_config() -> None:
        root.after(0, editor.show)

    # ── Status window ─────────────────────────────────────────────────────────
    window = StatusWindow(
        root,
        status,
        config,
        get_config=lambda: handle.config,
        on_manual_scan=manual_scan_event.set,
        on_open_config=open_config,
        on_exit=exit_event.set,
        theme_state=theme,
        pause_event=pause_event,
        on_edit_recipients=open_recipients,
    )

    # ── Tray icon ─────────────────────────────────────────────────────────────
    def _show_from_tray() -> None:
        root.after(0, window.show)

    tray = TrayIcon(
        on_exit_requested=exit_event.set,
        on_open_status=_show_from_tray,
    )
    tray.start()

    # ── Show window on startup ────────────────────────────────────────────────
    root.after(0, window.show)

    # ── Watchdog thread ───────────────────────────────────────────────────────
    def _watchdog() -> None:
        def _maybe_reload() -> None:
            # Re-check under the main thread to avoid racing with GUI-triggered reloads.
            if handle.is_dead():
                _reload_notifier(handle.config)

        while not exit_event.wait(5):
            # Restart notifier if it died unexpectedly.
            if handle.is_dead():
                LOGGER.warning("Notifier died; restarting", extra={"category": "startup"})
                root.after(0, _maybe_reload)
            # Restart tray icon if its run loop exited unexpectedly (e.g. after
            # system suspend/resume or a Win32 message-queue error).
            if not tray.is_running() and not exit_event.is_set():
                LOGGER.warning("Tray icon died; restarting", extra={"category": "startup"})
                try:
                    tray.stop()
                    tray.start()
                except Exception as exc:
                    LOGGER.exception(
                        "Failed to restart tray icon: %s",
                        exc,
                        extra={"category": "startup"},
                    )

    Thread(target=_watchdog, daemon=True, name="gui-watchdog").start()

    # ── Exit poller ───────────────────────────────────────────────────────────
    def _check_exit() -> None:
        if exit_event.is_set():
            handle.stop.set()
            with contextlib.suppress(Exception):
                root.quit()
            return
        root.after(300, _check_exit)

    root.after(300, _check_exit)

    # ── Run mainloop ──────────────────────────────────────────────────────────
    try:
        root.mainloop()
    except Exception:
        LOGGER.exception("GUI mainloop error", extra={"category": "startup"})
    finally:
        handle.stop.set()
        with contextlib.suppress(Exception):
            handle.thread.join(timeout=15)
        # Destroy Tk explicitly here — before Python's interpreter-level shutdown
        # — so Tcl's finalizer runs while the main thread is in a clean state.
        # Leaving root alive causes a hang when Python's GC calls root.__del__
        # after the Tcl/Tk DLLs have already started tearing down.
        with contextlib.suppress(Exception):
            root.destroy()
        # Stop the tray icon in a daemon thread; pystray's stop() joins its own
        # setup thread (up to 5 s) so we must not block the main thread here.
        Thread(target=tray.stop, daemon=True, name="tray-cleanup-final").start()
