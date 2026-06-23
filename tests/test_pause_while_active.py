"""Tests for automatic scan pause/unpause based on user idle state."""

from __future__ import annotations

from pathlib import Path
from threading import Event, Thread
import time

import pytest

from z7_sentineltray import app
from z7_sentineltray.app import Notifier
from z7_sentineltray.config import (
    AppConfig,
    EmailConfig,
    MonitorConfig,
    get_user_data_dir,
    get_user_log_dir,
)
from z7_sentineltray.status import StatusStore


def _config() -> AppConfig:
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
        subject="Z7_SentinelTray",
        retry_attempts=0,
        retry_backoff_seconds=0,
    )
    return AppConfig(
        poll_interval_seconds=1,
        healthcheck_interval_seconds=3600,
        error_backoff_base_seconds=5,
        error_backoff_max_seconds=300,
        debounce_seconds=0,
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
        min_repeat_seconds=0,
        error_notification_cooldown_seconds=300,
        window_error_backoff_base_seconds=5,
        window_error_backoff_max_seconds=120,
        window_error_circuit_threshold=3,
        window_error_circuit_seconds=300,
        email_queue_file=str(log_root / "email_queue.json"),
        email_queue_max_items=1,
        email_queue_max_age_seconds=0,
        email_queue_max_attempts=0,
        email_queue_retry_base_seconds=0,
        pause_on_user_active=True,
        pause_idle_threshold_seconds=180,
        monitors=[
            MonitorConfig(
                window_title_regex="APP",
                phrase_regex="ALERT",
                email=email,
            )
        ],
    )


class _FakeSender:
    def send(self, _message: str) -> None:
        pass


def test_scan_skipped_when_user_is_active(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """scan_once should not be called when user is active (idle < threshold)."""
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    config = _config()
    notifier = Notifier(config=config, status=StatusStore())
    notifier._sender = _FakeSender()  # type: ignore[assignment]

    monkeypatch.setattr(app, "get_idle_seconds", lambda: 10.0)

    stop_event = Event()
    scan_calls: list[int] = []

    def fake_scan_once() -> None:
        scan_calls.append(1)
        stop_event.set()

    notifier.scan_once = fake_scan_once  # type: ignore[assignment]

    telemetry_calls: list[int] = []

    def fake_update_telemetry() -> None:
        telemetry_calls.append(1)
        if len(telemetry_calls) >= 2:
            stop_event.set()

    notifier._update_telemetry = fake_update_telemetry  # type: ignore[assignment]

    notifier.run_loop(stop_event)

    assert len(scan_calls) == 0
    assert notifier.status.snapshot().last_scan_result == "PAUSADO (usuário ativo)"


def test_scan_runs_when_user_is_idle(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """scan_once should be called when user has been idle longer than the threshold."""
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    config = _config()
    notifier = Notifier(config=config, status=StatusStore())
    notifier._sender = _FakeSender()  # type: ignore[assignment]

    monkeypatch.setattr(app, "get_idle_seconds", lambda: 200.0)

    stop_event = Event()
    scan_calls: list[int] = []

    def fake_scan_once() -> None:
        scan_calls.append(1)
        stop_event.set()

    notifier.scan_once = fake_scan_once  # type: ignore[assignment]

    notifier.run_loop(stop_event)

    assert len(scan_calls) == 1


def test_scan_runs_when_pause_disabled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """scan_once should run regardless of idle state when pause_on_user_active is False."""
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    from dataclasses import replace

    base_config = _config()
    config = replace(base_config, pause_on_user_active=False)
    notifier = Notifier(config=config, status=StatusStore())
    notifier._sender = _FakeSender()  # type: ignore[assignment]

    monkeypatch.setattr(app, "get_idle_seconds", lambda: 5.0)

    stop_event = Event()
    scan_calls: list[int] = []

    def fake_scan_once() -> None:
        scan_calls.append(1)
        stop_event.set()

    notifier.scan_once = fake_scan_once  # type: ignore[assignment]

    notifier.run_loop(stop_event)

    assert len(scan_calls) == 1


def test_manual_scan_bypasses_pause(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A manual scan request must bypass the active-user pause."""
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    config = _config()
    notifier = Notifier(config=config, status=StatusStore())
    notifier._sender = _FakeSender()  # type: ignore[assignment]

    monkeypatch.setattr(app, "get_idle_seconds", lambda: 5.0)

    stop_event = Event()
    scan_calls: list[int] = []

    def fake_scan_once() -> None:
        scan_calls.append(1)
        stop_event.set()

    notifier.scan_once = fake_scan_once  # type: ignore[assignment]

    # patch _update_telemetry to also stop the loop as backup
    telemetry_calls: list[int] = []

    def fake_update_telemetry() -> None:
        telemetry_calls.append(1)
        if len(telemetry_calls) >= 2:
            stop_event.set()

    notifier._update_telemetry = fake_update_telemetry  # type: ignore[assignment]

    manual_scan_event = Event()
    manual_scan_event.set()

    notifier.run_loop(stop_event, manual_scan_event)

    assert len(scan_calls) == 1


class _RecordingSender:
    def __init__(self) -> None:
        self.sent_messages: list[str] = []

    def send(self, message: str) -> None:
        self.sent_messages.append(message)


def test_user_active_warning_email_sent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Warning email should be sent exactly once when entering user-active paused state."""
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    config = _config()
    notifier = Notifier(config=config, status=StatusStore())

    sender = _RecordingSender()
    notifier._sender = sender  # type: ignore[assignment]

    # We mock get_idle_seconds to change over time
    idle_values = [10.0, 10.0, 200.0, 10.0]  # Active, Active, Idle, Active

    def get_next_idle() -> float:
        if idle_values:
            return idle_values.pop(0)
        return 200.0

    monkeypatch.setattr(app, "get_idle_seconds", get_next_idle)

    stop_event = Event()

    # We want to run the loop for 4 iterations.
    # Since _update_telemetry is called once at startup, we wait for 5 calls in total.
    telemetry_calls = 0

    def fake_update_telemetry() -> None:
        nonlocal telemetry_calls
        telemetry_calls += 1
        if telemetry_calls >= 5:
            stop_event.set()

    notifier._update_telemetry = fake_update_telemetry  # type: ignore[assignment]
    notifier.scan_once = lambda: None  # type: ignore[assignment]

    notifier.run_loop(stop_event)

    assert len(sender.sent_messages) == 1
    assert "aviso:" in sender.sent_messages[0]
    assert "segurança contra acesso não autorizado" in sender.sent_messages[0]


def test_user_active_warning_email_not_sent_on_resume(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Warning email should not be sent immediately when resuming from manual pause while user is active."""
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    config = _config()
    notifier = Notifier(config=config, status=StatusStore())

    sender = _RecordingSender()
    notifier._sender = sender  # type: ignore[assignment]

    # User is active: idle = 10s
    monkeypatch.setattr(app, "get_idle_seconds", lambda: 10.0)

    stop_event = Event()
    pause_event = Event()
    pause_event.set()  # Start paused

    # Run in a background thread and then resume
    thread = Thread(
        target=notifier.run_loop,
        args=(stop_event, None, None, None, pause_event),
    )
    thread.start()

    try:
        time.sleep(0.3)
        # Verify it is paused
        assert notifier.status.snapshot().paused is True

        # Clear manual pause (resume)
        pause_event.clear()

        # Wait a moment for loop iteration to process unpaused state
        time.sleep(0.3)

        # Stop loop
        stop_event.set()
        thread.join(timeout=2)

        # No warning email should be sent, because unpausing starts/resumes automatic monitoring
        # and at this transition the warning is suppressed even if user is active.
        assert len(sender.sent_messages) == 0
    finally:
        stop_event.set()
        pause_event.clear()
        if thread.is_alive():
            thread.join(timeout=1)


def test_user_active_warning_email_not_sent_after_manual_scan(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Warning email should not be sent after a manual scan when user is active."""
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    config = _config()
    notifier = Notifier(config=config, status=StatusStore())

    sender = _RecordingSender()
    notifier._sender = sender  # type: ignore[assignment]

    # User is active: idle = 10s
    monkeypatch.setattr(app, "get_idle_seconds", lambda: 10.0)

    stop_event = Event()
    manual_scan_event = Event()
    manual_scan_event.set()  # Trigger manual scan

    telemetry_calls = 0

    def fake_update_telemetry() -> None:
        nonlocal telemetry_calls
        telemetry_calls += 1
        # Stop after 2 telemetry calls (1 at startup, 1 after first loop iteration)
        if telemetry_calls >= 3:
            stop_event.set()

    notifier._update_telemetry = fake_update_telemetry  # type: ignore[assignment]
    notifier.scan_once = lambda: None  # type: ignore[assignment]

    notifier.run_loop(stop_event, manual_scan_event)

    # First iteration was manual scan (user active, warning is not sent because is_manual).
    # Second iteration was user active (warning should be suppressed because _was_paused_by_user_active is True).
    assert not any("aviso:" in msg for msg in sender.sent_messages)

