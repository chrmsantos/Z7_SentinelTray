from __future__ import annotations

from threading import Event

import pytest

import z7_sentineltray.app
from z7_sentineltray.app import Notifier, _safe_status_text
from z7_sentineltray.config import (
    AppConfig,
    EmailConfig,
    MonitorConfig,
    get_user_data_dir,
    get_user_log_dir,
)
from z7_sentineltray.detector import WindowUnavailableError, WindowTextDetector
from z7_sentineltray.status import StatusStore


def test_run_loop_skips_window_unavailable(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    base = get_user_data_dir()
    log_root = get_user_log_dir()
    email = EmailConfig(
        smtp_host="smtp.local",
        smtp_port=587,
        smtp_username="",
        smtp_password="",
        from_address="alerts@example.com",
        to_addresses=["ops@example.com"],
        use_tls=True,
        timeout_seconds=10,
        subject="Z7_SentinelTray Notification",
        retry_attempts=0,
        retry_backoff_seconds=0,
    )
    config = AppConfig(
        poll_interval_seconds=1,
        healthcheck_interval_seconds=3600,
        error_backoff_base_seconds=5,
        error_backoff_max_seconds=300,
        debounce_seconds=600,
        max_history=10,
        state_file=str(base / "state.json"),
        log_file=str(log_root / "z7_sentineltray.log"),
        log_level="INFO",
        log_console_level="WARNING",
        log_console_enabled=False,
        log_max_bytes=5000000,
        log_backup_count=3,
        log_run_files_keep=3,
        telemetry_file=str(log_root / "telemetry.json"),
        allow_window_restore=True,
        log_only_mode=False,
        send_repeated_matches=True,
        pause_on_user_active=False,
        monitors=[
            MonitorConfig(
                window_title_regex="APP",
                phrase_regex="ALERT",
                email=email,
            )
        ],
    )

    notifier = Notifier(config=config, status=StatusStore())
    stop_event = Event()

    def fake_scan_once() -> None:
        raise WindowUnavailableError("Target window not enabled")

    notifier.scan_once = fake_scan_once  # type: ignore[assignment]

    sends = {"count": 0}

    class FakeSender:
        def send(self, _message: str) -> None:
            sends["count"] += 1

    notifier._sender = FakeSender()  # type: ignore[assignment]

    calls = {"count": 0}

    def fake_update_telemetry() -> None:
        calls["count"] += 1
        if calls["count"] >= 2:
            stop_event.set()

    notifier._update_telemetry = fake_update_telemetry  # type: ignore[assignment]

    notifier.run_loop(stop_event)

    snapshot = notifier.status.snapshot()
    assert snapshot.error_count == 0
    assert snapshot.last_error
    # window-unavailable error notification (1)
    assert sends["count"] == 1


def test_window_unavailable_when_screen_locked(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    base = get_user_data_dir()
    log_root = get_user_log_dir()
    email = EmailConfig(
        smtp_host="smtp.local",
        smtp_port=587,
        smtp_username="",
        smtp_password="",
        from_address="alerts@example.com",
        to_addresses=["ops@example.com"],
        use_tls=True,
        timeout_seconds=10,
        subject="Z7_SentinelTray Notification",
        retry_attempts=0,
        retry_backoff_seconds=0,
    )
    config = AppConfig(
        poll_interval_seconds=1,
        healthcheck_interval_seconds=3600,
        error_backoff_base_seconds=5,
        error_backoff_max_seconds=300,
        debounce_seconds=600,
        max_history=10,
        state_file=str(base / "state.json"),
        log_file=str(log_root / "z7_sentineltray.log"),
        log_level="INFO",
        log_console_level="WARNING",
        log_console_enabled=False,
        log_max_bytes=5000000,
        log_backup_count=3,
        log_run_files_keep=3,
        telemetry_file=str(log_root / "telemetry.json"),
        allow_window_restore=True,
        log_only_mode=False,
        send_repeated_matches=True,
        pause_on_user_active=False,
        monitors=[
            MonitorConfig(
                window_title_regex="APP",
                phrase_regex="ALERT",
                email=email,
            )
        ],
    )

    notifier = Notifier(config=config, status=StatusStore())
    stop_event = Event()

    def fake_scan_once() -> None:
        raise WindowUnavailableError("Target window not enabled")

    notifier.scan_once = fake_scan_once  # type: ignore[assignment]

    sends = []

    class FakeSender:
        def send(self, message: str) -> None:
            sends.append(message)

    notifier._sender = FakeSender()  # type: ignore[assignment]

    monkeypatch.setattr(z7_sentineltray.app, "is_screen_locked", lambda: True)

    calls = {"count": 0}

    def fake_update_telemetry() -> None:
        calls["count"] += 1
        if calls["count"] >= 2:
            stop_event.set()

    notifier._update_telemetry = fake_update_telemetry  # type: ignore[assignment]

    notifier.run_loop(stop_event)

    snapshot = notifier.status.snapshot()
    assert snapshot.error_count == 0
    assert snapshot.last_error == _safe_status_text("erro: janela indisponível: Target window not enabled (a tela do usuário do windows está bloqueada)")
    assert len(sends) == 1
    assert _safe_status_text(" (a tela do usuário do windows está bloqueada)") in sends[0]


def test_scan_once_window_unavailable_when_screen_locked(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    base = get_user_data_dir()
    log_root = get_user_log_dir()
    email = EmailConfig(
        smtp_host="smtp.local",
        smtp_port=587,
        smtp_username="",
        smtp_password="",
        from_address="alerts@example.com",
        to_addresses=["ops@example.com"],
        use_tls=True,
        timeout_seconds=10,
        subject="Z7_SentinelTray Notification",
        retry_attempts=0,
        retry_backoff_seconds=0,
    )
    config = AppConfig(
        poll_interval_seconds=1,
        healthcheck_interval_seconds=3600,
        error_backoff_base_seconds=5,
        error_backoff_max_seconds=300,
        debounce_seconds=600,
        max_history=10,
        state_file=str(base / "state.json"),
        log_file=str(log_root / "z7_sentineltray.log"),
        log_level="INFO",
        log_console_level="WARNING",
        log_console_enabled=False,
        log_max_bytes=5000000,
        log_backup_count=3,
        log_run_files_keep=3,
        telemetry_file=str(log_root / "telemetry.json"),
        allow_window_restore=True,
        log_only_mode=False,
        send_repeated_matches=True,
        pause_on_user_active=False,
        monitors=[
            MonitorConfig(
                window_title_regex="APP",
                phrase_regex="ALERT",
                email=email,
            )
        ],
    )

    notifier = Notifier(config=config, status=StatusStore())

    def fake_find_matches(_self, _regex: str) -> list[str]:
        raise WindowUnavailableError("Target window not found")

    monkeypatch.setattr(WindowTextDetector, "find_matches", fake_find_matches)

    monkeypatch.setattr(z7_sentineltray.app, "is_screen_locked", lambda: True)

    sends = []

    class FakeSender:
        def send(self, message: str) -> None:
            sends.append(message)

    notifier._sender = FakeSender()  # type: ignore[assignment]

    notifier.scan_once()

    snapshot = notifier.status.snapshot()
    assert snapshot.last_error == _safe_status_text("erro: janela indisponível: Target window not found (a tela do usuário do windows está bloqueada)")
    assert len(sends) == 1
    assert " (a tela do usuário do windows está bloqueada)" in sends[0]

