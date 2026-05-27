"""Module to handle checking and downloading application updates from GitHub."""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import tkinter as tk
import urllib.request
from pathlib import Path
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .gui_app import _ThemeState

LOGGER = logging.getLogger(__name__)

# GitHub URL definitions
_REPO_API_URL = "https://api.github.com/repos/chrmsantos/z7_sentineltray/releases/latest"


def parse_version(v_str: str) -> tuple[int, ...]:
    """Parse version string into a comparable tuple of integers.

    Args:
        v_str: The version string (e.g., "6.1.5" or "v6.2.0").

    Returns:
        A tuple of integers representing the version number.
    """
    if v_str.lower().startswith("v"):
        v_str = v_str[1:]
    v_str = v_str.replace("-", ".")
    parts = []
    for part in v_str.split("."):
        digits = "".join(c for c in part if c.isdigit())
        if digits:
            parts.append(int(digits))
    return tuple(parts)


class UpdateProgressWindow:
    """Toplevel Tkinter window showing the download progress of the update."""

    def __init__(
        self,
        parent: tk.Tk | tk.Toplevel,
        theme_state: _ThemeState,
        download_url: str,
        dest_path: Path,
    ) -> None:
        """Initialize the download progress window and start download thread.

        Args:
            parent: The parent Tkinter window.
            theme_state: The current theme state of the application.
            download_url: The URL to download the update from.
            dest_path: The local destination path for the executable.
        """
        self.parent = parent
        self.theme = theme_state
        self.download_url = download_url
        self.dest_path = dest_path

        self.win = tk.Toplevel(parent)
        self.win.title("Baixando Atualização")
        self.win.resizable(False, False)
        self.win.transient(parent)
        self.win.grab_set()

        # UI variables
        self.progress_var = tk.DoubleVar(value=0.0)
        self.status_var = tk.StringVar(value="Iniciando download...")

        # Color palette
        self.palette = self.theme.palette
        self.win.configure(bg=self.palette["bg"])

        self._build_ui()

        self.cancel_event = threading.Event()
        self.download_thread = threading.Thread(target=self._run_download, daemon=True)
        self.download_thread.start()

        self.win.protocol("WM_DELETE_WINDOW", self.on_cancel)
        self.win.bind("<Escape>", lambda _e: self.on_cancel())

    def _build_ui(self) -> None:
        p = self.palette

        # Top banner frame
        header_frame = tk.Frame(self.win, bg=p["surface"], pady=12)
        header_frame.pack(fill=tk.X)

        tk.Label(
            header_frame,
            text="🚀  Atualização do Sistema",
            font=("Segoe UI", 11, "bold"),
            fg=p["green"],
            bg=p["surface"],
        ).pack(anchor="w", padx=16)

        tk.Frame(self.win, bg=p["border"], height=1).pack(fill=tk.X)

        # Body frame
        body = tk.Frame(self.win, bg=p["bg"], padx=20, pady=16)
        body.pack(fill=tk.BOTH, expand=True)

        self.status_lbl = tk.Label(
            body,
            textvariable=self.status_var,
            font=("Segoe UI", 9),
            fg=p["text"],
            bg=p["bg"],
            anchor="w",
            justify="left",
            wraplength=360,
        )
        self.status_lbl.pack(fill=tk.X, pady=(0, 12))

        # Progressbar
        self.progress = ttk.Progressbar(
            body,
            orient="horizontal",
            length=360,
            mode="determinate",
            variable=self.progress_var,
        )
        self.progress.pack(fill=tk.X, pady=(0, 16))

        # Separator and Footer with Cancel button
        tk.Frame(self.win, bg=p["border"], height=1).pack(fill=tk.X)
        footer = tk.Frame(self.win, bg=p["surface"], pady=8)
        footer.pack(fill=tk.X)

        cancel_btn = tk.Button(
            footer,
            text="Cancelar",
            command=self.on_cancel,
            font=("Segoe UI", 9, "bold"),
            fg=p["white"],
            bg="#5a1a1a",
            activeforeground=p["white"],
            activebackground="#5a1a1a",
            relief=tk.FLAT,
            cursor="hand2",
            padx=14,
            pady=5,
            bd=0,
        )
        cancel_btn.pack(side=tk.RIGHT, padx=16)

        def on_enter(_e: tk.Event) -> None:
            cancel_btn.configure(bg="#802020", activebackground="#802020")

        def on_leave(_e: tk.Event) -> None:
            cancel_btn.configure(bg="#5a1a1a", activebackground="#5a1a1a")

        cancel_btn.bind("<Enter>", on_enter)
        cancel_btn.bind("<Leave>", on_leave)

        # Center the window relative to parent
        self.win.update_idletasks()
        w, h = 400, 190
        px = self.parent.winfo_x() + (self.parent.winfo_width() - w) // 2
        py = self.parent.winfo_y() + (self.parent.winfo_height() - h) // 2
        self.win.geometry(f"{w}x{h}+{px}+{py}")

    def on_cancel(self) -> None:
        """Prompt user for confirmation when canceling the download."""
        if self.cancel_event.is_set():
            return
        if messagebox.askyesno(
            "Cancelar Download",
            "Deseja realmente cancelar o download da atualização?",
            parent=self.win,
        ):
            self.cancel_event.set()
            self.status_var.set("Cancelando...")
            self.win.after(200, self.win.destroy)

    def _run_download(self) -> None:
        temp_dest = self.dest_path.with_suffix(".tmp_download")
        try:
            req = urllib.request.Request(
                self.download_url, headers={"User-Agent": "Z7_SentinelTray-Updater"}
            )
            with urllib.request.urlopen(req, timeout=30) as response:
                total_size = int(response.info().get("Content-Length", 0))
                bytes_downloaded = 0
                block_size = 16384

                with open(temp_dest, "wb") as f:
                    while not self.cancel_event.is_set():
                        block = response.read(block_size)
                        if not block:
                            break
                        f.write(block)
                        bytes_downloaded += len(block)

                        percent = (bytes_downloaded / total_size) * 100 if total_size else 0
                        speed_msg = (
                            f"Baixando: {percent:.1f}% "
                            f"({bytes_downloaded // 1024} KB / {total_size // 1024} KB)"
                        )
                        self.win.after(
                            0, lambda p=percent, m=speed_msg: self._update_ui_state(p, m)
                        )

            if self.cancel_event.is_set():
                if temp_dest.exists():
                    temp_dest.unlink(missing_ok=True)
                return

            # Request finalization in main GUI thread
            self.win.after(0, lambda: self.status_var.set("Instalando atualização..."))
            self.win.after(0, lambda: self._finalize_update(temp_dest))

        except Exception as exc:
            if temp_dest.exists():
                temp_dest.unlink(missing_ok=True)
            LOGGER.exception("Failed to download update")
            self.win.after(0, lambda e=exc: self._handle_error(e))

    def _update_ui_state(self, percent: float, msg: str) -> None:
        if self.win.winfo_exists():
            self.progress_var.set(percent)
            self.status_var.set(msg)

    def _finalize_update(self, temp_dest: Path) -> None:
        try:
            is_frozen = getattr(sys, "frozen", False)
            if not is_frozen:
                from .config import get_project_root

                # Dev mode target path simulation
                dev_dest = get_project_root() / "dist" / "Z7_SentinelTray.exe"
                dev_dest.parent.mkdir(parents=True, exist_ok=True)
                if dev_dest.exists():
                    dev_dest.unlink()
                os.rename(temp_dest, dev_dest)
                messagebox.showinfo(
                    "Atualização (Desenvolvimento)",
                    f"Modo de desenvolvimento detectado!\n\n"
                    f"O download foi realizado com sucesso.\n"
                    f"O executável simulado foi salvo em:\n{dev_dest}\n\n"
                    f"A atualização real de sys.executable não foi realizada "
                    f"para evitar danificar o interpretador python.",
                    parent=self.parent,
                )
                self.win.destroy()
                return

            current_exe = Path(sys.executable)
            old_exe = current_exe.with_suffix(".exe.old")

            # Rename current running executable first
            if old_exe.exists():
                try:
                    old_exe.unlink()
                except Exception:
                    import time

                    old_exe = current_exe.with_name(f"Z7_SentinelTray.exe.old.{int(time.time())}")

            os.rename(current_exe, old_exe)
            os.rename(temp_dest, current_exe)

            messagebox.showinfo(
                "Atualização Concluída",
                "A atualização foi baixada e instalada com sucesso!\n\n"
                "A nova versão será efetivada na próxima execução do aplicativo.",
                parent=self.parent,
            )
            self.win.destroy()
        except Exception as exc:
            LOGGER.exception("Failed to install update")
            if temp_dest.exists():
                temp_dest.unlink(missing_ok=True)
            messagebox.showerror(
                "Erro na Instalação",
                f"Erro ao instalar a atualização:\n{exc}",
                parent=self.parent,
            )
            self.win.destroy()

    def _handle_error(self, exc: Exception) -> None:
        messagebox.showerror(
            "Erro no Download",
            f"Não foi possível baixar a atualização:\n{exc}",
            parent=self.parent,
        )
        self.win.destroy()


def run_update_check(
    parent: tk.Tk | tk.Toplevel, theme_state: _ThemeState, current_version: str
) -> None:
    """Check for updates on GitHub and launch download if accepted by the user.

    Args:
        parent: The parent Tkinter window.
        theme_state: The current theme state of the application.
        current_version: The current version of the application.
    """

    def do_check() -> None:
        try:
            req = urllib.request.Request(
                _REPO_API_URL, headers={"User-Agent": "Z7_SentinelTray-Updater"}
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode("utf-8"))

            if data.get("prerelease") or data.get("draft"):
                parent.after(
                    0,
                    lambda: messagebox.showinfo(
                        "Atualização", "Você já está na versão mais recente.", parent=parent
                    ),
                )
                return

            tag_name: str = data.get("tag_name", "")
            if not tag_name:
                parent.after(
                    0,
                    lambda: messagebox.showinfo(
                        "Atualização", "Você já está na versão mais recente.", parent=parent
                    ),
                )
                return

            # Find executable asset
            exe_asset: dict[str, Any] | None = None
            for asset in data.get("assets", []):
                asset_name: str = asset.get("name", "")
                if asset_name.lower().endswith(".exe") or asset_name == "Z7_SentinelTray":
                    exe_asset = asset
                    break

            if not exe_asset:
                parent.after(
                    0,
                    lambda: messagebox.showwarning(
                        "Atualização",
                        f"A versão {tag_name} está disponível, mas nenhum executável "
                        f"compatível foi encontrado no GitHub.",
                        parent=parent,
                    ),
                )
                return

            if parse_version(tag_name) <= parse_version(current_version):
                parent.after(
                    0,
                    lambda: messagebox.showinfo(
                        "Atualização",
                        "Você já está na versão estável mais recente do aplicativo.",
                        parent=parent,
                    ),
                )
                return

            # New version found! Ask user
            download_url: str = exe_asset.get("browser_download_url", "")
            filename: str = exe_asset.get("name", "")
            release_name: str = data.get("name", tag_name)

            def ask_user() -> None:
                msg = (
                    f"Uma nova atualização estável está disponível!\n\n"
                    f"Versão: {tag_name} ({release_name})\n"
                    f"Arquivo: {filename}\n\n"
                    f"Deseja realizar o download e atualizar agora?"
                )
                if messagebox.askyesno("Atualização Disponível", msg, parent=parent):
                    dest_path = Path(sys.executable)
                    UpdateProgressWindow(parent, theme_state, download_url, dest_path)

            parent.after(0, ask_user)

        except Exception as exc:
            LOGGER.exception("Failed to check for updates")
            parent.after(
                0,
                lambda e=exc: messagebox.showerror(
                    "Erro de Verificação",
                    f"Erro ao verificar atualizações:\n{e}",
                    parent=parent,
                ),
            )

    threading.Thread(target=do_check, daemon=True).start()
