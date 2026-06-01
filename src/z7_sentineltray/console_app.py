"""Console (non-GUI) front-end for running and configuring Z7_SentinelTray."""

from __future__ import annotations

import contextlib
import logging
import msvcrt
import os
import subprocess
import sys
import time
import webbrowser
from builtins import input as input
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC
from pathlib import Path
from threading import Event, Thread

from .app import Notifier
from .config import (
    AppConfig,
    get_config_template_path,
    get_project_root,
    get_user_data_dir,
    get_user_log_dir,
    load_config,
)
from .detector import WindowTextDetector
from .dpapi_utils import save_secret
from .gui_app import prompt_smtp_password_gui
from .status import StatusStore, format_timestamp
from .tray_app import TrayIcon

LOGGER = logging.getLogger(__name__)

_PROJECT_REPO_URL = "https://github.com/chrmsantos/z7_sentineltray"


def _clear_stored_smtp_password(index: int) -> None:
    env_key = f"Z7_SENTINELTRAY_SMTP_PASSWORD_{index}"
    if env_key in os.environ:
        os.environ.pop(env_key, None)
    secret_path = get_user_data_dir() / f"smtp_password_{index}.dpapi"
    if not secret_path.exists():
        return
    try:
        secret_path.unlink()
    except Exception as exc:
        LOGGER.warning(
            "Failed to clear stored SMTP password for monitor %s: %s",
            index,
            exc,
            extra={"category": "config"},
        )


def _prune_files(path: Path, pattern: str, keep: int = 3) -> None:
    entries = sorted(
        path.glob(pattern),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    for entry in entries[keep:]:
        try:
            entry.unlink()
        except Exception:
            continue


def _start_notifier(
    config: AppConfig,
    status: StatusStore,
    stop_event: Event,
    manual_scan_event: Event,
    scan_complete_event: Event | None = None,
    test_message_event: Event | None = None,
) -> Thread:
    notifier = Notifier(config=config, status=status)
    thread = Thread(
        target=notifier.run_loop,
        args=(stop_event, manual_scan_event, scan_complete_event, test_message_event),
        daemon=True,
    )
    thread.start()
    return thread


def _apply_console_logging_policy(config: AppConfig) -> AppConfig:
    if not config.log_console_enabled:
        return config
    return replace(config, log_console_enabled=False)


def _create_config_editor() -> tuple[  # noqa: C901
    Callable[[], None],
    Callable[[], AppConfig | None],
    Callable[[], None],
]:
    edit_process: subprocess.Popen[str] | None = None

    def config_path() -> Path:
        return get_user_data_dir() / "config.local.yaml"

    def on_open() -> None:
        nonlocal edit_process
        if edit_process is not None and edit_process.poll() is None:
            return
        try:
            target_path = config_path()
            if not target_path.exists():
                target_path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    template_content = get_config_template_path().read_text(encoding="utf-8")
                except Exception:
                    template_content = None
                if template_content is None:
                    template_content = (
                        "# Z7_SentinelTray - configuração local\n"
                        "# Preencha os campos obrigatórios antes de rodar.\n"
                    )
                target_path.write_text(template_content, encoding="utf-8")
            edit_process = subprocess.Popen(["notepad.exe", str(target_path)], text=True)
        except Exception as exc:
            LOGGER.warning("Failed to open config editor: %s", exc)

    def finalize_config_edit() -> AppConfig | None:
        nonlocal edit_process
        if edit_process is None:
            return
        if edit_process.poll() is None:
            return
        edit_process = None
        try:
            target_path = config_path()
            if not target_path.exists():
                return
            try:
                new_config = load_config(str(target_path))
            except Exception as exc:
                LOGGER.warning("Config validation failed after edit: %s", exc)
                return None
            else:
                return new_config
        except Exception as exc:
            LOGGER.warning("Failed to finalize config edit: %s", exc)
        return None

    def close_editor() -> None:
        nonlocal edit_process
        if edit_process is None:
            return
        if edit_process.poll() is None:
            try:
                edit_process.terminate()
                edit_process.wait(timeout=2)
            except Exception:
                with contextlib.suppress(Exception):
                    edit_process.kill()
        edit_process = None

    return on_open, finalize_config_edit, close_editor


def _write_config_error_details(message: str) -> Path:
    log_dir = get_user_log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / "config_error.txt"
    if path.exists():
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        rotated = log_dir / f"config_error.{timestamp}.txt"
        with contextlib.suppress(Exception):
            path.rename(rotated)
    path.write_text(message.strip() + "\n", encoding="utf-8")
    _prune_files(log_dir, "config_error*.txt", keep=3)
    return path


def _open_text_file(path: Path) -> None:
    try:
        subprocess.Popen(["notepad.exe", str(path)])
    except Exception as exc:
        LOGGER.warning("Failed to open details: %s", exc)


def clear_screen() -> None:
    """Clear the terminal screen using the platform-appropriate command."""
    os.system("cls" if os.name == "nt" else "clear")


def _email_address_lines(config: AppConfig) -> list[str]:
    lines = []
    for index, monitor in enumerate(config.monitors, start=1):
        sender_addr = monitor.email.from_address or monitor.email.smtp_username or "??"
        recipients = ", ".join(monitor.email.to_addresses) if monitor.email.to_addresses else "??"
        lines.append(f"Monitor {index}: {sender_addr} -> {recipients}")
    return lines


def _format_next_scan_remaining(last_scan: str, poll_interval_seconds: int) -> str:
    if not last_scan or not poll_interval_seconds:
        return "NENHUM"
    try:
        from datetime import datetime, timedelta

        last = datetime.fromisoformat(last_scan)
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        now = datetime.now(UTC)
        remaining = (last + timedelta(seconds=poll_interval_seconds) - now).total_seconds()
        if remaining <= 0:
            return "iminente"
        minutes, seconds = divmod(int(remaining), 60)
        if minutes > 0:
            return f"{minutes}m {seconds:02d}s"
    except (ValueError, TypeError):
        return "NENHUM"
    else:
        return f"{seconds}s"


def _menu_header(status: StatusStore, config: AppConfig) -> list[str]:
    snapshot = status.snapshot()
    state = "EXECUTANDO" if snapshot.running else "PARADO"
    last_send_at = format_timestamp(snapshot.last_send)
    last_message = f"ENVIADA ({last_send_at})" if last_send_at else "NENHUMA"
    last_scan_at = format_timestamp(snapshot.last_scan)
    last_scan_line = f"Ultimo scan: {last_scan_at or 'NENHUM'}"
    last_scan_result_line = f"Resultado scan: {snapshot.last_scan_result or 'NENHUM'}"
    next_scan_remaining = _format_next_scan_remaining(
        snapshot.last_scan, config.poll_interval_seconds
    )
    next_scan_line = f"Proximo scan em: {next_scan_remaining}"
    last_error_line = f"Ultimo erro: {snapshot.last_error or 'NENHUM'}"
    queue = snapshot.email_queue
    queue_line = (
        "Fila e-mail: "
        f"{queue.get('queued', 0)} pendentes, "
        f"{queue.get('deferred', 0)} atrasados, "
        f"{queue.get('failed', 0)} falhas"
    )
    breaker_line = f"Monitores em breaker: {snapshot.breaker_active_count}"
    failures = [(key, count) for key, count in snapshot.monitor_failures.items() if count > 0]
    failures.sort(key=lambda item: item[1], reverse=True)
    failure_line = ""
    if failures:
        summary = []
        for key, count in failures[:3]:
            label = key if len(key) <= 20 else f"{key[:17]}..."
            summary.append(f"{label}={count}")
        failure_line = "Falhas por monitor: " + ", ".join(summary)
    return [
        "Z7_SentinelTray - Console",
        f"Status atual: {state}",
        f"ERROS: {snapshot.error_count}",
        *_email_address_lines(config),
        last_scan_line,
        last_scan_result_line,
        next_scan_line,
        f"Última mensagem: {last_message}",
        last_error_line,
        queue_line,
        breaker_line,
        failure_line,
        "",
    ]


def _print_window_matches(config: AppConfig) -> None:
    print("Janelas correspondentes por monitor:")
    print("")
    for index, monitor in enumerate(config.monitors, start=1):
        detector = WindowTextDetector(
            monitor.window_title_regex,
            allow_window_restore=False,
            log_throttle_seconds=0,
        )
        try:
            titles = detector.list_matching_window_titles()
        except Exception as exc:
            print(f"Monitor {index}: erro ao listar janelas: {exc}")
            continue
        if not titles:
            print(f"Monitor {index}: nenhuma janela corresponde ({monitor.window_title_regex})")
            continue
        print(
            f"Monitor {index}: {len(titles)} janela(s) encontrada(s) ({monitor.window_title_regex})"
        )
        for title in titles[:5]:
            print(f"  - {title}")
        if len(titles) > 5:
            print(f"  ... e mais {len(titles) - 5}")
    print("")
    input("Enter para voltar...")


def _read_command(prompt: str, refresh_event: Event, exit_event: Event | None = None) -> str | None:
    """Read a command from the console with auto-refresh support.

    Returns the typed command string, or None if the display should refresh
    (scan_complete_event fired before the user started typing).
    Returns "q" immediately if exit_event is set (e.g. from the tray icon).
    """
    sys.stdout.write(prompt)
    sys.stdout.flush()
    buf: list[str] = []
    while True:
        if exit_event is not None and exit_event.is_set():
            sys.stdout.write("\n")
            sys.stdout.flush()
            return "q"
        if refresh_event.is_set():
            refresh_event.clear()
            if not buf:
                sys.stdout.write("\n")
                sys.stdout.flush()
                return None
        if msvcrt.kbhit():
            ch = msvcrt.getwch()
            if ch in ("\x00", "\xe0"):
                msvcrt.getwch()  # consume second byte of extended key sequence
            elif ch in ("\r", "\n"):
                sys.stdout.write("\n")
                sys.stdout.flush()
                return "".join(buf)
            elif ch == "\x03":  # Ctrl+C
                raise KeyboardInterrupt
            elif ch == "\x08":  # Backspace
                if buf:
                    buf.pop()
                    sys.stdout.write("\b \b")
                    sys.stdout.flush()
            elif ch >= " ":
                buf.append(ch)
                sys.stdout.write(ch)
                sys.stdout.flush()
        else:
            time.sleep(0.05)


def _update_smtp_credentials_console(config: AppConfig) -> None:
    """Prompt for updated SMTP credentials for all monitors and persist them."""
    print("\nAtualizar Credenciais SMTP")
    print("-" * 30)
    for index, monitor in enumerate(config.monitors, start=1):
        old_username = str(monitor.email.smtp_username or "").strip()
        old_from = str(monitor.email.from_address or "").strip()
        print(f"\nMonitor {index} — Usuário atual: {old_username or '(não definido)'}")
        try:
            new_username = input(f"  Novo usuário [{old_username}]: ").strip()
        except KeyboardInterrupt:
            print("\nCancelado.")
            return
        if not new_username:
            new_username = old_username
        password = prompt_smtp_password_gui(new_username, index)
        if password is None:
            print("  Senha não informada — mantendo a senha atual.")
            password = ""
        else:
            password = password.strip()
        if new_username != old_username:
            local_path = get_user_data_dir() / "config.local.yaml"
            try:
                yaml_text = local_path.read_text(encoding="utf-8")
                # Patch this single monitor's username
                monitors_count = len(config.monitors)
                all_usernames = [
                    new_username if i == index - 1 else str(m.email.smtp_username or "")
                    for i, m in enumerate(config.monitors)
                ]
                from .gui_app import _patch_from_address, _patch_smtp_username

                patched = _patch_smtp_username(yaml_text, all_usernames)
                if old_from == old_username:
                    all_from = [
                        new_username if i == index - 1 else str(m.email.from_address or "")
                        for i, m in enumerate(config.monitors)
                    ]
                    patched = _patch_from_address(patched, all_from)
                local_path.write_text(patched, encoding="utf-8")
                print(f"  Usuário atualizado para: {new_username}")
                if old_from == old_username:
                    print(f"  Remetente (from_address) sincronizado: {new_username}")
            except Exception as exc:
                LOGGER.warning("Failed to update SMTP username in config: %s", exc)
                print(f"  AVISO: falha ao atualizar usuário no config: {exc}")
        if password:
            os.environ[f"Z7_SENTINELTRAY_SMTP_PASSWORD_{index}"] = password
            try:
                secret_path = get_user_data_dir() / f"smtp_password_{index}.dpapi"
                save_secret(secret_path, password)
                print("  Senha salva com segurança (DPAPI).")
            except Exception as exc:
                LOGGER.warning("Failed to store SMTP password securely: %s", exc)
                print(f"  AVISO: falha ao salvar senha: {exc}")
    print("")


def run_console(config: AppConfig) -> None:  # noqa: C901
    """Start the interactive console loop with tray icon support."""
    status = StatusStore()
    stop_event = Event()
    manual_scan_event = Event()
    scan_complete_event = Event()
    test_message_event = Event()
    _tray_exit_event = Event()
    config = _apply_console_logging_policy(config)
    notifier_thread = _start_notifier(
        config, status, stop_event, manual_scan_event, scan_complete_event, test_message_event
    )
    tray = TrayIcon(on_exit_requested=_tray_exit_event.set)
    tray.start()
    on_open, finalize_config_edit, close_editor = _create_config_editor()
    last_auth_error = ""

    def save_config_edit() -> AppConfig | None:
        return finalize_config_edit()

    def apply_config_edit() -> None:
        nonlocal config, notifier_thread, stop_event
        new_config = save_config_edit()
        if new_config is None:
            return
        config = new_config
        stop_event.set()
        try:
            notifier_thread.join(timeout=5)
        except Exception as exc:
            LOGGER.warning("Failed to stop notifier for config reload: %s", exc)
        stop_event = Event()
        status.set_last_error("")
        notifier_thread = _start_notifier(
            config,
            status,
            stop_event,
            manual_scan_event,
            scan_complete_event,
            test_message_event,
        )

    try:
        while True:
            snapshot = status.snapshot()
            if not notifier_thread.is_alive() and not stop_event.is_set():
                LOGGER.warning(
                    "Notifier thread died unexpectedly; restarting",
                    extra={"category": "startup"},
                )
                status.set_last_error("")
                stop_event = Event()
                notifier_thread = _start_notifier(
                    config,
                    status,
                    stop_event,
                    manual_scan_event,
                    scan_complete_event,
                    test_message_event,
                )
            if "smtp auth failed" in snapshot.last_error and snapshot.last_error != last_auth_error:
                last_auth_error = snapshot.last_error
                stop_event.set()
                try:
                    notifier_thread.join(timeout=5)
                except Exception as exc:
                    LOGGER.warning("Failed to stop notifier for SMTP reset: %s", exc)
                print("\nFalha de autenticação SMTP detectada.")
                print("Informe a senha correta para continuar.\n")
                updated_any = False
                for index, monitor in enumerate(config.monitors, start=1):
                    username = str(monitor.email.smtp_username or "").strip()
                    if not username:
                        continue
                    _clear_stored_smtp_password(index)
                    password = prompt_smtp_password_gui(username, index)
                    if not password or not password.strip():
                        continue
                    password = password.strip()
                    os.environ[f"Z7_SENTINELTRAY_SMTP_PASSWORD_{index}"] = password
                    updated_any = True
                    try:
                        secret_path = get_user_data_dir() / f"smtp_password_{index}.dpapi"
                        save_secret(secret_path, password)
                    except Exception as exc:
                        LOGGER.warning(
                            "Failed to store SMTP password securely: %s",
                            exc,
                            extra={"category": "config"},
                        )
                if updated_any:
                    local_path = get_user_data_dir() / "config.local.yaml"
                    try:
                        config = load_config(str(local_path))
                        status.set_last_error("")
                    except Exception as exc:
                        print(f"Falha ao validar config: {exc}")
                        time.sleep(2)
                stop_event = Event()
                status.set_last_error("")
                notifier_thread = _start_notifier(
                    config,
                    status,
                    stop_event,
                    manual_scan_event,
                    scan_complete_event,
                    test_message_event,
                )
            clear_screen()
            for line in _menu_header(status, config):
                print(line)
            print("Comandos:")
            print("  [C] Editar config")
            print("  [P] Credenciais SMTP")
            print("  [R] Repositório")
            print("  [Q] Sair")
            print("")
            try:
                raw_command = _read_command("Comando: ", scan_complete_event, _tray_exit_event)
            except KeyboardInterrupt:
                return
            if raw_command is None:
                apply_config_edit()
                continue
            command = raw_command.strip().lower()
            if command in ("q", "quit", "exit", "sair"):
                return
            if command in ("c", "config"):
                apply_config_edit()
                on_open()
            elif command in ("p", "smtp", "credenciais"):
                _update_smtp_credentials_console(config)
                local_path = get_user_data_dir() / "config.local.yaml"
                try:
                    config = load_config(str(local_path))
                    stop_event.set()
                    try:
                        notifier_thread.join(timeout=5)
                    except Exception as exc:
                        LOGGER.warning("Failed to stop notifier for SMTP reload: %s", exc)
                    stop_event = Event()
                    status.set_last_error("")
                    notifier_thread = _start_notifier(
                        config,
                        status,
                        stop_event,
                        manual_scan_event,
                        scan_complete_event,
                        test_message_event,
                    )
                except Exception as exc:
                    print(f"Falha ao recarregar config: {exc}")
                    time.sleep(2)
            elif command in ("r", "repo", "repositório", "repositorio"):
                webbrowser.open(_PROJECT_REPO_URL)
            apply_config_edit()
    except KeyboardInterrupt:
        return
    finally:
        stop_event.set()
        try:
            notifier_thread.join(timeout=5)
        finally:
            close_editor()
            save_config_edit()
            tray.stop()


def run_console_config_error(error_details: str) -> None:  # noqa: C901
    """Display a config-error recovery prompt and allow the user to fix the config."""
    on_open, finalize_config_edit, close_editor = _create_config_editor()
    details_path = _write_config_error_details(error_details)
    local_path = get_user_data_dir() / "config.local.yaml"
    supports_smtp_prompt = "Z7_SENTINELTRAY_SMTP_PASSWORD" in error_details
    smtp_usernames: list[tuple[int, str]] = []
    try:
        config = load_config(str(local_path))
        smtp_usernames = [
            (index, monitor.email.smtp_username)
            for index, monitor in enumerate(config.monitors, start=1)
            if monitor.email.smtp_username
        ]
    except Exception:
        smtp_usernames = []
    try:
        while True:
            clear_screen()
            print("Z7_SentinelTray - Erro de Configuração")
            print("")
            print(error_details)
            print("")
            print("Comandos:")
            print("  [C] Editar config")
            print("  [D] Abrir detalhes")
            if supports_smtp_prompt:
                print("  [P] Definir senha SMTP")
            print("  [Q] Sair")
            print("")
            try:
                command = input("Comando: ").strip().lower()
            except KeyboardInterrupt:
                return
            if command in ("q", "quit", "exit", "sair"):
                close_editor()
                return
            if command in ("c", "config"):
                on_open()
            elif command in ("d", "details", "detalhes"):
                _open_text_file(details_path)
            elif supports_smtp_prompt and command in ("p", "smtp"):
                print("")
                if smtp_usernames:
                    for index, username in smtp_usernames:
                        password = prompt_smtp_password_gui(username, index)
                        if not password or not password.strip():
                            continue
                        password = password.strip()
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
                else:
                    password = prompt_smtp_password_gui("(não definido no config)", 0)
                    if password and password.strip():
                        os.environ["Z7_SENTINELTRAY_SMTP_PASSWORD"] = password.strip()
                try:
                    config = load_config(str(local_path))
                except Exception as exc:
                    print(f"Falha ao validar config: {exc}")
                    time.sleep(2)
                    continue
                run_console(config)
                return
            finalize_config_edit()
    except KeyboardInterrupt:
        return
    finally:
        close_editor()
