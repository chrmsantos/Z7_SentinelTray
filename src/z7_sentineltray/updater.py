"""Module to handle checking and downloading application updates from GitHub."""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
import tkinter as tk
import urllib.error
import urllib.request
from pathlib import Path
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .gui_app import _ThemeState
    from .status import StatusStore

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


def check_write_permission(dest_path: Path) -> bool:
    """Check if the directory containing the destination path is writable.

    Args:
        dest_path: The file path to verify write access for.

    Returns:
        True if the parent directory is writable, False otherwise.
    """
    try:
        parent = dest_path.parent
        parent.mkdir(parents=True, exist_ok=True)
        # Try creating a dummy file in the directory
        temp_file = parent / f".write_test_{os.getpid()}"
        temp_file.touch()
        temp_file.unlink()
        return True
    except Exception:
        return False


def _get_target_path() -> Path:
    """Return the final target executable path based on whether the app is frozen or not."""
    is_frozen = getattr(sys, "frozen", False)
    if not is_frozen:
        from .config import get_project_root
        return get_project_root() / "dist" / "Z7_SentinelTray.exe"
    return Path(sys.executable)


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

        LOGGER.info(
            "Initializing UpdateProgressWindow (download_url=%s, dest_path=%s)...",
            self.download_url,
            self.dest_path,
            extra={"category": "update"},
        )
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
        LOGGER.info("User requested cancellation of the download.", extra={"category": "update"})
        if messagebox.askyesno(
            "Cancelar Download",
            "Deseja realmente cancelar o download da atualização?",
            parent=self.win,
        ):
            LOGGER.info("User confirmed download cancellation.", extra={"category": "update"})
            self.cancel_event.set()
            self.status_var.set("Cancelando...")
            self.win.after(200, self.win.destroy)

    def _run_download(self) -> None:
        temp_dest = self.dest_path.with_suffix(".tmp_download")
        try:
            LOGGER.info(
                "Starting download from %s to %s",
                self.download_url,
                temp_dest,
                extra={"category": "update"},
            )
            req = urllib.request.Request(
                self.download_url, headers={"User-Agent": "Z7_SentinelTray-Updater"}
            )
            with urllib.request.urlopen(req, timeout=30) as response:
                total_size = int(response.info().get("Content-Length", 0))
                LOGGER.info(
                    "Connected to download server. Expected total size: %s bytes",
                    total_size,
                    extra={"category": "update"},
                )
                bytes_downloaded = 0
                block_size = 16384
                last_logged_quarter = 0
                last_ui_update_time = 0.0
                last_percent = -1

                with open(temp_dest, "wb") as f:
                    while not self.cancel_event.is_set():
                        block = response.read(block_size)
                        if not block:
                            break
                        f.write(block)
                        bytes_downloaded += len(block)

                        percent = (bytes_downloaded / total_size) * 100 if total_size else 0
                        current_percent_int = int(percent)
                        now = time.time()

                        current_quarter = int(percent // 25) * 25
                        if current_quarter > last_logged_quarter and current_quarter <= 100:
                            LOGGER.info(
                                "Download progress: %d%% (%d/%d bytes)",
                                current_quarter,
                                bytes_downloaded,
                                total_size,
                                extra={"category": "update"},
                            )
                            last_logged_quarter = current_quarter

                        if current_percent_int != last_percent or (now - last_ui_update_time) >= 0.1:
                            speed_msg = (
                                f"Baixando: {percent:.1f}% "
                                f"({bytes_downloaded // 1024} KB / {total_size // 1024} KB)"
                            )
                            self.win.after(
                                0, lambda p=percent, m=speed_msg: self._update_ui_state(p, m)
                            )
                            last_percent = current_percent_int
                            last_ui_update_time = now

            if self.cancel_event.is_set():
                LOGGER.info(
                    "Download loop terminated due to cancellation. Cleaning up temporary file...",
                    extra={"category": "update"},
                )
                if temp_dest.exists():
                    temp_dest.unlink(missing_ok=True)
                return

            LOGGER.info(
                "Download completed successfully. Total size: %s bytes. Requesting finalization...",
                bytes_downloaded,
                extra={"category": "update"},
            )

            # Request finalization in main GUI thread
            self.win.after(0, lambda: self.status_var.set("Instalando atualização..."))
            self.win.after(0, lambda: self._finalize_update(temp_dest))

        except Exception as exc:
            LOGGER.exception("Failed to download update", extra={"category": "update"})
            if temp_dest.exists():
                temp_dest.unlink(missing_ok=True)
            self.win.after(0, lambda e=exc: self._handle_error(e))

    def _update_ui_state(self, percent: float, msg: str) -> None:
        if self.win.winfo_exists():
            self.progress_var.set(percent)
            self.status_var.set(msg)

    def _finalize_update(self, temp_dest: Path) -> None:
        try:
            is_frozen = getattr(sys, "frozen", False)
            if not is_frozen:
                LOGGER.info(
                    "Finalizing update in DEVELOPMENT mode. Simulating update process...",
                    extra={"category": "update"},
                )
                # Dev mode target path simulation
                dev_dest = self.dest_path
                dev_dest.parent.mkdir(parents=True, exist_ok=True)
                if dev_dest.exists():
                    LOGGER.info(
                        "Deleting existing simulated dev executable: %s",
                        dev_dest,
                        extra={"category": "update"},
                    )
                    dev_dest.unlink()
                os.rename(temp_dest, dev_dest)
                LOGGER.info(
                    "Development update simulation complete. Saved to %s",
                    dev_dest,
                    extra={"category": "update"},
                )
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

            current_exe = self.dest_path
            old_exe = current_exe.with_suffix(".exe.old")

            LOGGER.info(
                "Finalizing update in FROZEN mode. Target current executable: %s",
                current_exe,
                extra={"category": "update"},
            )

            # Rename current running executable first
            if old_exe.exists():
                try:
                    LOGGER.info(
                        "Removing existing old backup file: %s",
                        old_exe,
                        extra={"category": "update"},
                    )
                    old_exe.unlink()
                except Exception as unlink_err:
                    import time

                    old_exe = current_exe.with_name(f"Z7_SentinelTray.exe.old.{int(time.time())}")
                    LOGGER.warning(
                        "Failed to remove %s: %s. Using alternate old backup path: %s",
                        current_exe.with_suffix(".exe.old"),
                        unlink_err,
                        old_exe,
                        extra={"category": "update"},
                    )

            LOGGER.info(
                "Backing up current running executable: %s -> %s",
                current_exe,
                old_exe,
                extra={"category": "update"},
            )
            os.rename(current_exe, old_exe)
            LOGGER.info(
                "Installing newly downloaded executable: %s -> %s",
                temp_dest,
                current_exe,
                extra={"category": "update"},
            )
            try:
                os.rename(temp_dest, current_exe)
            except Exception as rename_exc:
                LOGGER.error(
                    "Failed to rename temp download to current exe. Restoring backup...",
                    exc_info=True,
                    extra={"category": "update"},
                )
                try:
                    os.rename(old_exe, current_exe)
                    LOGGER.info("Backup restored successfully.", extra={"category": "update"})
                except Exception as restore_exc:
                    LOGGER.critical(
                        "CRITICAL: Failed to restore backup executable: %s",
                        restore_exc,
                        exc_info=True,
                        extra={"category": "update"},
                    )
                raise rename_exc

            messagebox.showinfo(
                "Atualização Concluída",
                "A atualização foi baixada e instalada com sucesso!\n\n"
                "O aplicativo será reiniciado automaticamente na nova versão.",
                parent=self.parent,
            )
            self.win.destroy()

            # Release the single-instance mutex to allow the new process to start immediately
            from . import entrypoint
            import ctypes
            if entrypoint._mutex_handle:
                try:
                    LOGGER.info("Releasing single-instance Mutex...", extra={"category": "update"})
                    ctypes.windll.kernel32.CloseHandle(entrypoint._mutex_handle)
                    entrypoint._mutex_handle = None
                    LOGGER.info("Single-instance Mutex released successfully.", extra={"category": "update"})
                except Exception as mutex_err:
                    LOGGER.warning(
                        "Failed to close single-instance Mutex handle: %s",
                        mutex_err,
                        extra={"category": "update"},
                    )

            # Unlink PID file so the new instance starts cleanly
            try:
                pid_path = entrypoint._pid_file_path()
                if pid_path.exists():
                    LOGGER.info("Removing PID file: %s", pid_path, extra={"category": "update"})
                    pid_path.unlink()
                    LOGGER.info("PID file removed successfully.", extra={"category": "update"})
            except Exception as pid_err:
                LOGGER.warning(
                    "Failed to delete PID file: %s",
                    pid_err,
                    extra={"category": "update"},
                )

            # Launch the new version of the executable
            import subprocess
            try:
                # Remove PyInstaller-specific environment variables so that the restarted
                # process does not reuse the old process's extraction directory (_MEIPASS).
                env = os.environ.copy()
                if "_MEIPASS" in env:
                    env.pop("_MEIPASS")
                for key in list(env.keys()):
                    if key.startswith("_MEI"):
                        env.pop(key, None)
                LOGGER.info(
                    "Restarting application process: %s",
                    current_exe,
                    extra={"category": "update"},
                )
                subprocess.Popen([str(current_exe)], env=env)
                LOGGER.info("Restarted process spawned successfully.", extra={"category": "update"})
            except Exception as exc:
                LOGGER.exception("Failed to restart application after update", extra={"category": "update"})
                messagebox.showerror(
                    "Erro ao Reiniciar",
                    f"A atualização foi instalada com sucesso, mas ocorreu um erro ao reiniciar o aplicativo:\n{exc}",
                    parent=self.parent,
                )

            # Exit the current process gracefully by quitting the Tkinter mainloop
            try:
                LOGGER.info("Quitting old application Tkinter loop.", extra={"category": "update"})
                self.parent.quit()
            except Exception as quit_err:
                LOGGER.warning(
                    "Failed to quit Tkinter parent: %s. Falling back to sys.exit(0)",
                    quit_err,
                    extra={"category": "update"},
                )
                sys.exit(0)
        except Exception as exc:
            LOGGER.exception("Failed to install update", extra={"category": "update"})
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
    parent: tk.Tk | tk.Toplevel,
    theme_state: _ThemeState,
    current_version: str,
    on_startup: bool = False,
    status: StatusStore | None = None,
) -> None:
    """Check for updates on GitHub and launch download if accepted by the user.

    Args:
        parent: The parent Tkinter window.
        theme_state: The current theme state of the application.
        current_version: The current version of the application.
        on_startup: If True, do not show messages for "up to date" or network errors.
        status: The global thread-safe status store to update.
    """

    def do_check() -> None:
        if status:
            status.set_update_status("Verificando...")
        LOGGER.info(
            "Starting update check (on_startup=%s, current_version=%s)...",
            on_startup,
            current_version,
            extra={"category": "update"},
        )
        try:
            req = urllib.request.Request(
                _REPO_API_URL, headers={"User-Agent": "Z7_SentinelTray-Updater"}
            )
            LOGGER.debug(
                "Requesting latest release metadata from GitHub API: %s",
                _REPO_API_URL,
                extra={"category": "update"},
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode("utf-8"))

            LOGGER.info(
                "Successfully fetched release metadata from GitHub API.",
                extra={"category": "update"},
            )

            if data.get("prerelease") or data.get("draft"):
                LOGGER.info(
                    "Latest release is a prerelease or draft, skipping: tag=%s",
                    data.get("tag_name"),
                    extra={"category": "update"},
                )
                if status:
                    status.set_update_status("Atualizado")
                if not on_startup:
                    parent.after(
                        0,
                        lambda: messagebox.showinfo(
                            "Atualização", "Você já está na versão mais recente.", parent=parent
                        ),
                    )
                return

            tag_name: str = data.get("tag_name", "")
            if not tag_name:
                LOGGER.warning(
                    "Latest release metadata has no tag_name. Skipping update.",
                    extra={"category": "update"},
                )
                if status:
                    status.set_update_status("Atualizado")
                if not on_startup:
                    parent.after(
                        0,
                        lambda: messagebox.showinfo(
                            "Atualização", "Você já está na versão mais recente.", parent=parent
                        ),
                    )
                return

            LOGGER.info(
                "Latest release tag is %s. Checking assets for a compatible executable...",
                tag_name,
                extra={"category": "update"},
            )

            # Find executable asset
            exe_asset: dict[str, Any] | None = None
            for asset in data.get("assets", []):
                asset_name: str = asset.get("name", "")
                if asset_name.lower().endswith(".exe") or asset_name == "Z7_SentinelTray":
                    exe_asset = asset
                    break

            if not exe_asset:
                LOGGER.warning(
                    "Compatible executable asset (.exe or 'Z7_SentinelTray') not found in release %s assets.",
                    tag_name,
                    extra={"category": "update"},
                )
                if status:
                    status.set_update_status(f"Atualização disponível ({tag_name})")
                if not on_startup:
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

            LOGGER.info(
                "Found compatible asset: %s (size: %s bytes)",
                exe_asset.get("name"),
                exe_asset.get("size"),
                extra={"category": "update"},
            )

            if parse_version(tag_name) <= parse_version(current_version):
                LOGGER.info(
                    "Current version %s is up-to-date or newer than latest version %s. Skipping update.",
                    current_version,
                    tag_name,
                    extra={"category": "update"},
                )
                if status:
                    status.set_update_status("Atualizado")
                if not on_startup:
                    parent.after(
                        0,
                        lambda: messagebox.showinfo(
                            "Atualização",
                            "Você já está na versão estável mais recente do aplicativo.",
                            parent=parent,
                        ),
                    )
                return

            # New version found!
            LOGGER.info(
                "New update found! Version: %s (current: %s).",
                tag_name,
                current_version,
                extra={"category": "update"},
            )

            dest_path = _get_target_path()
            if not check_write_permission(dest_path):
                LOGGER.warning(
                    "Write permission denied in installation directory: %s. Cannot install update.",
                    dest_path.parent,
                    extra={"category": "update"},
                )
                if status:
                    status.set_update_status(f"Sem permissão de gravação ({tag_name})")
                if not on_startup:
                    parent.after(
                        0,
                        lambda: messagebox.showwarning(
                            "Permissão Negada",
                            f"Uma nova versão ({tag_name}) está disponível, mas o aplicativo não possui "
                            f"permissão de gravação no diretório de instalação:\n{dest_path.parent}\n\n"
                            f"Por favor, execute o aplicativo como administrador para atualizar.",
                            parent=parent,
                        ),
                    )
                return

            if status:
                status.set_update_status(f"Atualização disponível ({tag_name})")

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
                LOGGER.info(
                    "Prompting user for update acceptance: version=%s",
                    tag_name,
                    extra={"category": "update"},
                )
                if messagebox.askyesno("Atualização Disponível", msg, parent=parent):
                    LOGGER.info(
                        "User accepted the update. Spawning UpdateProgressWindow...",
                        extra={"category": "update"},
                    )
                    UpdateProgressWindow(parent, theme_state, download_url, dest_path)
                else:
                    LOGGER.info(
                        "User declined the update prompt.",
                        extra={"category": "update"},
                    )

            if not on_startup:
                parent.after(0, ask_user)

        except Exception as exc:
            # Check if this is a common network error to avoid tracebacks in logs when offline.
            is_network_err = False
            if isinstance(exc, urllib.error.URLError):
                is_network_err = True
            elif isinstance(exc, (TimeoutError, ConnectionError)):
                is_network_err = True
            elif hasattr(exc, "reason") and ("getaddrinfo failed" in str(exc) or "timed out" in str(exc)):
                is_network_err = True

            if is_network_err:
                LOGGER.warning(
                    "Failed to check for updates (network offline/timeout): %s",
                    exc,
                    extra={"category": "update"},
                )
            else:
                LOGGER.exception("Failed to check for updates due to unexpected error", extra={"category": "update"})

            if status:
                status.set_update_status("Erro ao verificar")
            if not on_startup:
                parent.after(
                    0,
                    lambda e=exc: messagebox.showerror(
                        "Erro de Verificação",
                        f"Erro ao verificar atualizações:\n{e}",
                        parent=parent,
                    ),
                )

    threading.Thread(target=do_check, daemon=True).start()
