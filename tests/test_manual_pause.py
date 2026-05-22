"""Tests for manual pause/resume execution state."""

from __future__ import annotations

from pathlib import Path
from threading import Event, Thread
import time

import pytest

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
        pause_on_user_active=False,
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


def test_manual_pause_suppresses_scan(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Notifier should not scan when manual pause is set, updating status to PAUSADO."""
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    config = _config()
    notifier = Notifier(config=config, status=StatusStore())
    notifier._sender = _FakeSender()  # type: ignore[assignment]

    stop_event = Event()
    pause_event = Event()
    pause_event.set()  # Start paused

    scan_calls: list[int] = []

    def fake_scan_once() -> None:
        scan_calls.append(1)

    notifier.scan_once = fake_scan_once  # type: ignore[assignment]

    # Run in a background thread so we can verify the state and stop it
    thread = Thread(
        target=notifier.run_loop,
        args=(stop_event, None, None, None, pause_event),
    )
    thread.start()

    try:
        # Give the loop a moment to start and register the pause
        time.sleep(0.3)
        snapshot = notifier.status.snapshot()
        assert snapshot.paused is True
        assert snapshot.last_scan_result == "PAUSADO"
        assert len(scan_calls) == 0
    finally:
        stop_event.set()
        pause_event.clear()  # Clear to avoid blocking join
        thread.join(timeout=2)


def test_manual_pause_resume_executes_scan(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Notifier should scan when manual pause is cleared (resumed)."""
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    config = _config()
    notifier = Notifier(config=config, status=StatusStore())
    notifier._sender = _FakeSender()  # type: ignore[assignment]

    stop_event = Event()
    pause_event = Event()
    pause_event.set()  # Start paused

    scan_calls: list[int] = []

    def fake_scan_once() -> None:
        scan_calls.append(1)
        stop_event.set()  # Stop as soon as scan is triggered

    notifier.scan_once = fake_scan_once  # type: ignore[assignment]

    thread = Thread(
        target=notifier.run_loop,
        args=(stop_event, None, None, None, pause_event),
    )
    thread.start()

    try:
        time.sleep(0.3)
        assert len(scan_calls) == 0

        # Resume execution
        pause_event.clear()

        # Wait for scan to trigger and stop the loop
        thread.join(timeout=2)
        assert len(scan_calls) == 1
        assert notifier.status.snapshot().paused is False
    finally:
        stop_event.set()
        pause_event.clear()
        if thread.is_alive():
            thread.join(timeout=1)
