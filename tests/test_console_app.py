from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from z7_sentineltray import console_app
from z7_sentineltray.config import AppConfig, EmailConfig, MonitorConfig
from z7_sentineltray.status import StatusStore


def _make_config(tmp_path: Path) -> AppConfig:
    email = EmailConfig(
        smtp_host="",
        smtp_port=587,
        smtp_username="",
        smtp_password="",
        from_address="",
        to_addresses=[],
        use_tls=True,
        timeout_seconds=10,
        subject="Z7_SentinelTray",
        retry_attempts=1,
        retry_backoff_seconds=1,
    )
    monitor = MonitorConfig(
        window_title_regex="EXEMPLO",
        phrase_regex="ALERTA",
        email=email,
    )
    return AppConfig(
        poll_interval_seconds=10,
        healthcheck_interval_seconds=0,
        error_backoff_base_seconds=5,
        error_backoff_max_seconds=30,
        debounce_seconds=10,
        max_history=10,
        state_file=str(tmp_path / "state.json"),
        log_file=str(tmp_path / "logs" / "z7_sentineltray.log"),
        log_level="INFO",
        log_console_level="WARNING",
        log_console_enabled=True,
        log_max_bytes=1000000,
        log_backup_count=1,
        log_run_files_keep=5,
        telemetry_file=str(tmp_path / "logs" / "telemetry.json"),
        allow_window_restore=True,
        log_only_mode=True,
        send_repeated_matches=True,
        monitors=[monitor],
    )


def test_run_console_exit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("Z7_SENTINELTRAY_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(console_app, "clear_screen", lambda: None)
    calls: dict[str, Any] = {"finalize": 0, "opened": 0, "joined": False}
    notifier_configs: list[AppConfig] = []

    def fake_create_editor():
        def on_open() -> None:
            calls["opened"] += 1

        def finalize() -> None:
            calls["finalize"] += 1

        def close_editor() -> None:
            return None

        return on_open, finalize, close_editor

    class DummyThread:
        def is_alive(self) -> bool:
            return True

        def join(self, timeout: float | None = None) -> None:
            calls["joined"] = True

    monkeypatch.setattr(console_app, "_create_config_editor", fake_create_editor)

    def fake_start_notifier(config: AppConfig, *_args: object, **_kwargs: object) -> DummyThread:
        notifier_configs.append(config)
        return DummyThread()

    monkeypatch.setattr(console_app, "_start_notifier", fake_start_notifier)

    class DummyTray:
        def start(self) -> None:
            pass

        def stop(self) -> None:
            pass

    monkeypatch.setattr(console_app, "TrayIcon", lambda **_kwargs: DummyTray())

    def noop_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(console_app.time, "sleep", noop_sleep)

    inputs: Iterator[str] = iter(["q"])

    def fake_read_command(
        _prompt: str, _refresh_event: object, _exit_event: object = None
    ) -> str | None:
        return next(inputs)

    monkeypatch.setattr(console_app, "_read_command", fake_read_command)

    console_app.run_console(_make_config(tmp_path))

    assert calls["joined"] is True
    assert notifier_configs
    assert notifier_configs[0].log_console_enabled is False


def test_run_console_config_error_details(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("Z7_SENTINELTRAY_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(console_app, "clear_screen", lambda: None)
    monkeypatch.setattr(
        console_app,
        "_create_config_editor",
        lambda: (lambda: None, lambda: None, lambda: None),
    )

    opened: dict[str, Path] = {}

    def fake_open(path: Path) -> None:
        opened["path"] = path

    monkeypatch.setattr(console_app, "_open_text_file", fake_open)

    inputs: Iterator[str] = iter(["d", "q"])

    def fake_input(_prompt: str) -> str:
        return next(inputs)

    monkeypatch.setattr(console_app, "input", fake_input)

    console_app.run_console_config_error("details")

    assert "path" in opened


def test_run_console_config_error_smtp_prompt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("Z7_SENTINELTRAY_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(console_app, "clear_screen", lambda: None)
    monkeypatch.setattr(
        console_app,
        "_create_config_editor",
        lambda: (lambda: None, lambda: None, lambda: None),
    )

    inputs: Iterator[str] = iter(["p"])

    def fake_input(_prompt: str) -> str:
        return next(inputs)

    monkeypatch.setattr(console_app, "input", fake_input)
    monkeypatch.setattr(console_app, "prompt_smtp_password_gui", lambda _user, _idx: "smtp-pass")

    config = _make_config(tmp_path)
    calls: dict[str, Any] = {"config": None}

    def fake_load(_path: str) -> AppConfig:
        return config

    def fake_run_console(value: AppConfig) -> None:
        calls["config"] = value

    monkeypatch.setattr(console_app, "load_config", fake_load)
    monkeypatch.setattr(console_app, "run_console", fake_run_console)

    console_app.run_console_config_error("Missing Z7_SENTINELTRAY_SMTP_PASSWORD")

    assert os.environ["Z7_SENTINELTRAY_SMTP_PASSWORD"] == "smtp-pass"
    assert calls["config"] is config


def test_menu_header_status_lines(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    status = StatusStore()
    status.set_running(True)
    status.increment_error_count()
    status.set_last_send("2026-02-03T10:00:00-03:00")
    status.set_email_queue_stats(
        {
            "queued": 2,
            "sent": 1,
            "failed": 0,
            "deferred": 1,
            "oldest_age_seconds": 120,
        }
    )

    header = console_app._menu_header(status, config)

    assert "Status atual: EXECUTANDO" in header
    assert "ERROS: 1" in header
    assert "Última mensagem: ENVIADA (03-02-2026 - 10:00)" in header
    assert "Fila e-mail: 2 pendentes, 1 atrasados, 0 falhas" in header
