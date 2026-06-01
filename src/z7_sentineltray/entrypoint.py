"""Application entrypoint: single-instance guard, startup checks, and UI launch."""

from __future__ import annotations

import atexit
import contextlib
import ctypes
import hashlib
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import __release_date__, __version_label__
from .config import AppConfig, get_config_template_path, get_project_root, get_user_data_dir, get_user_log_dir, load_config
from .logging_setup import setup_logging

LOGGER = logging.getLogger(__name__)
_mutex_handle = None


def _load_config_template() -> str:
    """Return the contents of config.local.yaml.example as the default template.

    Raises FileNotFoundError if the example file cannot be located.
    """
    try:
        return get_config_template_path().read_text(encoding="utf-8")
    except Exception as exc:
        raise FileNotFoundError(
            "Config template not found. Expected config/config.local.yaml.example "
            "alongside the application."
        ) from exc


def _pid_file_path() -> Path:
    base = get_user_data_dir()
    return base / "z7_sentineltray.pid"


def _show_already_running_notice() -> None:
    message = "Z7_SentinelTray já está em execução.\n\n"
    try:
        ctypes.windll.user32.MessageBoxW(
            None,
            message,
            "Z7_SentinelTray",
            0x00000040,
        )
    except Exception:
        sys.stderr.write(f"{message}\n")


def _ensure_single_instance_mutex() -> bool:
    global _mutex_handle
    try:
        kernel32 = ctypes.windll.kernel32
    except Exception:
        return True
    # Incorporate the project root into the mutex name so that different
    # installations (e.g. separate test sandboxes) don't interfere with
    # each other while still preventing two instances from the same root.
    root_hash = hashlib.sha256(str(get_project_root()).encode()).hexdigest()[:8]
    for scope in ("Global", "Local"):
        name = f"{scope}\\Z7_SentinelTrayMutex_{root_hash}"
        try:
            mutex = kernel32.CreateMutexW(None, False, name)
            _mutex_handle = mutex
            if kernel32.GetLastError() == 183:
                return False
            if mutex:
                LOGGER.info(
                    "Single-instance mutex acquired: %s",
                    name,
                    extra={"category": "startup"},
                )
                return True
        except Exception as exc:
            LOGGER.warning(
                "Failed to create mutex %s: %s",
                name,
                exc,
                extra={"category": "startup"},
            )
            continue
    return True


def _ensure_single_instance() -> None:
    if not _ensure_single_instance_mutex():
        _show_already_running_notice()
        raise SystemExit(0)
    pid_path = _pid_file_path()
    pid_path.parent.mkdir(parents=True, exist_ok=True)

    pid_path.write_text(str(os.getpid()), encoding="utf-8")

    def _cleanup() -> None:
        try:
            if pid_path.exists() and pid_path.read_text(encoding="utf-8").strip() == str(
                os.getpid()
            ):
                pid_path.unlink()
        except Exception:
            return

    atexit.register(_cleanup)


def _get_process_name(pid: int) -> str | None:
    """Return the executable name of the given PID, or None if it cannot be determined."""
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().splitlines():
                line = line.strip()
                if line.startswith('"'):
                    return line.split('"')[1].lower()
    except Exception:
        pass
    return None


def _terminate_existing_instance() -> bool:
    pid_path = _pid_file_path()
    if not pid_path.exists():
        LOGGER.warning(
            "Single-instance mutex exists but PID file is missing",
            extra={"category": "startup"},
        )
        return False
    try:
        prior_pid = pid_path.read_text(encoding="utf-8").strip()
    except Exception as exc:
        LOGGER.warning(
            "Failed to read PID file for termination: %s",
            exc,
            extra={"category": "startup"},
        )
        return False
    if not prior_pid:
        LOGGER.warning(
            "PID file was empty; cannot terminate prior instance",
            extra={"category": "startup"},
        )
        return False
    try:
        pid_value = int(prior_pid)
        if pid_value < 2:
            raise ValueError(f"PID {pid_value!r} is implausibly low")
    except ValueError as exc:
        LOGGER.warning(
            "PID file contains invalid value %r: %s",
            prior_pid,
            exc,
            extra={"category": "startup"},
        )
        return False
    process_name = _get_process_name(pid_value)
    if (
        process_name is not None
        and "z7_sentineltray" not in process_name
        and "python" not in process_name
    ):
        LOGGER.warning(
            "PID %s belongs to '%s', not Z7_SentinelTray; "
            "skipping termination to avoid killing an unrelated process",
            pid_value,
            process_name,
            extra={"category": "startup"},
        )
        return False
    LOGGER.info(
        "Existing instance detected; terminating PID %s",
        pid_value,
        extra={"category": "startup"},
    )
    try:
        result = subprocess.run(
            ["taskkill", "/PID", str(pid_value), "/F"],
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception:
        LOGGER.exception(
            "Failed to terminate prior instance PID %s",
            prior_pid,
            extra={"category": "startup"},
        )
        return False
    if result.returncode != 0:
        LOGGER.error(
            "taskkill failed for PID %s: %s",
            prior_pid,
            result.stderr.strip(),
            extra={"category": "startup"},
        )
        return False
    with contextlib.suppress(Exception):
        pid_path.unlink()
    return True


def _ensure_local_override(path: Path) -> None:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_load_config_template(), encoding="utf-8")
        LOGGER.info(
            "Config template created at %s",
            path,
            extra={"category": "config"},
        )
        with contextlib.suppress(Exception):
            subprocess.Popen(["notepad.exe", str(path)])
        raise SystemExit(
            "Configuration template created.\n"
            f"File: {path}\n"
            "Fill in your values (SMTP host, credentials, window title, etc.), "
            "save, and restart Z7_SentinelTray."
        )

    content = path.read_text(encoding="utf-8").strip()
    if not content:
        raise SystemExit(
            "Local configuration is empty.\n"
            f"File: {path}\n"
            "Fill the required fields, save, and run again."
        )


def _handle_config_error(path: Path, exc: Exception) -> str:
    reason = str(exc)
    message = (
        "Configuration error.\n\n"
        f"Config file: {path}\n"
        f"Details: {reason}\n\n"
        "Review the YAML formatting and required fields.\n"
        "After fixing, reopen Z7_SentinelTray.\n\n"
        "Quick actions:\n"
        "- Use the console menu: Config (opens an editable temporary file).\n"
        "- Use the console menu: Detalhes (shows this message).\n"
        "- For test mode only, set email.dry_run=true.\n"
    )
    LOGGER.error("Config error: %s", reason, extra={"category": "config"})
    return message


def _reject_extra_args(args: list[str]) -> None:
    if not args:
        return
    if args[0] in ("--version", "-V"):
        from . import __release_date__, __version_label__

        print(f"Z7_SentinelTray {__version_label__}  ({__release_date__})")
        raise SystemExit(0)
    if args[0] in ("--help", "-h"):
        print(
            "Z7_SentinelTray — monitor de janelas com alertas por e-mail.\n"
            "\n"
            "Uso: python main.py [--version | --help]\n"
            "  --version, -V   Exibe versão e encerra.\n"
            "  --help,    -h   Exibe esta ajuda e encerra.\n"
        )
        raise SystemExit(0)
    raise SystemExit(
        f"Usage: run Z7_SentinelTray without arguments.\nArguments received: {' '.join(args)}"
    )


def _setup_boot_logging() -> None:
    if logging.getLogger().handlers:
        return
    try:
        log_root = get_user_log_dir()
        log_root.mkdir(parents=True, exist_ok=True)
        boot_log = log_root / "z7_sentineltray_boot.log"
        setup_logging(
            str(boot_log),
            log_level="INFO",
            log_console_level="INFO",
            log_console_enabled=True,
            log_max_bytes=1_000_000,
            log_backup_count=3,
            log_run_files_keep=3,
            app_version=__version_label__,
            release_date=__release_date__,
            commit_hash="",
        )
    except Exception as exc:
        logging.basicConfig(level=logging.INFO)
        logging.getLogger(__name__).warning(
            "Boot logging unavailable; using stderr: %s",
            exc,
            extra={"category": "startup"},
        )


def _legacy_data_dir() -> Path | None:
    candidates: list[Path] = []
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        candidates.append(Path(local_appdata) / "ZWave" / "Z7_SentinelTray" / "config")
    else:
        user_root = os.environ.get("USERPROFILE")
        if user_root:
            candidates.append(
                Path(user_root)
                / "AppData"
                / "Local"
                / "ZWave"
                / "Tmp"
                / "Z7_SentinelTray"
                / "Config"
            )
    candidates.append(get_project_root() / "config")
    for candidate in candidates:
        if (candidate / "config.local.yaml").exists():
            return candidate
    return None


def _migrate_legacy_config(local_path: Path) -> None:
    legacy_dir = _legacy_data_dir()
    if legacy_dir is None:
        return
    legacy_config = legacy_dir / "config.local.yaml"
    if not legacy_config.exists():
        return
    if local_path.exists():
        try:
            if local_path.read_text(encoding="utf-8").strip():
                return
        except Exception:
            return
    local_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(legacy_config, local_path)
        LOGGER.info(
            "Migrated legacy config to project scope",
            extra={"category": "config", "legacy_path": str(legacy_config)},
        )
    except Exception as exc:
        LOGGER.warning(
            "Failed to migrate legacy config: %s",
            exc,
            extra={"category": "config"},
        )


def _run_startup_integrity_checks(local_path: Path) -> None:
    data_dir = local_path.parent
    data_dir.mkdir(parents=True, exist_ok=True)
    log_root = get_user_log_dir()
    log_root.mkdir(parents=True, exist_ok=True)
    sentinel = data_dir / "migration.done"
    if not sentinel.exists():
        _migrate_legacy_config(local_path)
        with contextlib.suppress(Exception):
            sentinel.write_text("1", encoding="utf-8")


def _clear_stored_smtp_password(index: int) -> None:
    env_key = f"Z7_SENTINELTRAY_SMTP_PASSWORD_{index}"
    if env_key in os.environ:
        os.environ.pop(env_key, None)
    secret_path = get_user_data_dir() / f"smtp_password_{index}.dpapi"
    if not secret_path.exists():
        return
    try:
        secret_path.unlink()
        LOGGER.info(
            "Cleared stored SMTP password for monitor %s",
            index,
            extra={"category": "config"},
        )
    except Exception as exc:
        LOGGER.warning(
            "Failed to clear stored SMTP password for monitor %s: %s",
            index,
            exc,
            extra={"category": "config"},
        )


def _validate_smtp_config(config: AppConfig) -> tuple[list[tuple[int, str]], list[str]]:
    from .email_sender import EmailAuthError, validate_smtp_credentials

    auth_failures: list[tuple[int, str]] = []
    auth_messages: list[str] = []
    failures: list[str] = []
    if config.log_only_mode:
        return auth_failures, auth_messages
    for index, monitor in enumerate(config.monitors, start=1):
        email = monitor.email
        try:
            validate_smtp_credentials(email)
        except EmailAuthError as exc:
            auth_failures.append((index, email.smtp_username))
            auth_messages.append(f"monitor {index}: {exc}")
        except Exception as exc:
            failures.append(f"monitor {index}: {exc}")
    if failures:
        raise ValueError("SMTP validation failed: " + "; ".join(failures))
    return auth_failures, auth_messages


def _ensure_windows() -> None:
    if sys.platform == "win32":
        return
    LOGGER.error(
        "Unsupported platform: %s (Z7_SentinelTray requires Windows)",
        sys.platform,
        extra={"category": "startup"},
    )
    raise SystemExit("Z7_SentinelTray requires Windows.")


def _missing_smtp_passwords(config: AppConfig) -> list[tuple[int, str]]:
    missing: list[tuple[int, str]] = []
    global_password = os.environ.get("Z7_SENTINELTRAY_SMTP_PASSWORD", "").strip()
    for index, monitor in enumerate(config.monitors, start=1):
        username = str(monitor.email.smtp_username or "").strip()
        if not username:
            continue
        if str(monitor.email.smtp_password or "").strip():
            continue
        indexed_password = os.environ.get(f"Z7_SENTINELTRAY_SMTP_PASSWORD_{index}", "").strip()
        if indexed_password or global_password:
            continue
        missing.append((index, username))
    return missing


def _prompt_smtp_passwords(missing: list[tuple[int, str]]) -> None:
    from .dpapi_utils import save_secret
    from .gui_app import prompt_smtp_password_gui

    if not missing:
        return
    for index, username in missing:
        while True:
            password = prompt_smtp_password_gui(username, index)
            if password is None:
                raise SystemExit("Senha SMTP não informada.")
            password = password.strip()
            if password:
                os.environ[f"Z7_SENTINELTRAY_SMTP_PASSWORD_{index}"] = password
                try:
                    secret_path = get_user_data_dir() / f"smtp_password_{index}.dpapi"
                    save_secret(secret_path, password)
                except Exception as exc:
                    LOGGER.warning(
                        "Failed to store SMTP password securely: %s",
                        exc,
                        extra={"category": "config"},
                    )
                break


def _first_run_gui_setup(path: Path) -> None:
    """Write the config template and open the GUI editor for first-run setup.

    Raises SystemExit if the user closes the editor without saving.
    """
    import tkinter as tk

    from .gui_app import ConfigEditorWindow

    template_content = _load_config_template()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(template_content, encoding="utf-8")
    LOGGER.info(
        "Config template created at %s for first-run setup",
        path,
        extra={"category": "config"},
    )

    saved: list[bool] = [False]

    root = tk.Tk()
    root.withdraw()

    def on_saved(cfg: AppConfig) -> None:
        saved[0] = True

    editor = ConfigEditorWindow(root, on_saved=on_saved)
    editor.show()
    if editor._win is not None:
        root.wait_window(editor._win)
    with contextlib.suppress(Exception):
        root.destroy()

    if not saved[0]:
        raise SystemExit(
            "Z7_SentinelTray requer configuração para iniciar.\n"
            f"Arquivo: {path}\n"
            "Preencha os valores e salve para iniciar o Z7_SentinelTray."
        )


def main() -> int:  # noqa: C901
    """Parse CLI args, load configuration, and launch the appropriate UI."""
    _setup_boot_logging()
    _ensure_single_instance()
    args = [arg for arg in sys.argv[1:] if arg]
    _reject_extra_args(args)

    from .splash import SplashScreen

    splash = SplashScreen()

    local_path = get_user_data_dir() / "config.local.yaml"
    config = None
    config_error_message = None
    try:
        _ensure_windows()
        _run_startup_integrity_checks(local_path)
        if not local_path.exists():
            splash.close()
            _first_run_gui_setup(local_path)
        _ensure_local_override(local_path)
        config = load_config(str(local_path))
        missing_passwords = _missing_smtp_passwords(config)
        if missing_passwords:
            splash.close()
            _prompt_smtp_passwords(missing_passwords)
            config = load_config(str(local_path))
    except Exception as exc:
        config_error_message = _handle_config_error(local_path, exc)

    splash.close()

    try:
        if config_error_message is not None:
            from .console_app import run_console_config_error

            run_console_config_error(config_error_message)
        else:
            if config is None:
                raise SystemExit("Configuration not loaded.")

            _captured_local_path = local_path

            def _smtp_validator(root: object, config_holder: list, reload_notifier: object) -> None:
                import threading

                def _bg() -> None:
                    try:
                        auth_failures, _ = _validate_smtp_config(config_holder[0])
                    except Exception:
                        LOGGER.exception(
                            "SMTP validation error during startup",
                            extra={"category": "config"},
                        )
                        return
                    if not auth_failures:
                        return

                    def _reprompt() -> None:
                        for index, _ in auth_failures:
                            _clear_stored_smtp_password(index)
                        try:
                            _prompt_smtp_passwords(auth_failures)
                        except SystemExit:
                            return
                        try:
                            new_cfg = load_config(str(_captured_local_path))
                        except Exception:
                            LOGGER.exception(
                                "Failed to reload config after SMTP re-prompt",
                                extra={"category": "config"},
                            )
                            return
                        reload_notifier(new_cfg)

                    root.after(0, _reprompt)

                threading.Thread(target=_bg, daemon=True, name="smtp-validator").start()

            from .gui_app import run_gui

            run_gui(config, smtp_validator=_smtp_validator)
    except Exception:
        LOGGER.exception("Failed to start console UI", extra={"category": "startup"})
        raise SystemExit("Failed to start console UI.") from None
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
