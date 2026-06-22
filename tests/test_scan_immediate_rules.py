from __future__ import annotations

import pytest

from z7_sentineltray.app import Notifier
from z7_sentineltray.config import AppConfig, EmailConfig, MonitorConfig
from z7_sentineltray.detector import WindowTextDetector
from z7_sentineltray.email_sender import EmailSender
from z7_sentineltray.status import StatusStore


def _config() -> AppConfig:
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
        state_file="state.json",
        log_file="logs/z7_sentineltray.log",
        log_level="INFO",
        log_console_level="WARNING",
        log_console_enabled=True,
        log_max_bytes=5000000,
        log_backup_count=5,
        log_run_files_keep=5,
        telemetry_file="logs/telemetry.json",
        allow_window_restore=True,
        log_only_mode=False,
        send_repeated_matches=True,
        min_repeat_seconds=0,
        error_notification_cooldown_seconds=300,
        window_error_backoff_base_seconds=5,
        window_error_backoff_max_seconds=120,
        window_error_circuit_threshold=3,
        window_error_circuit_seconds=300,
        email_queue_file="logs/email_queue.json",
        email_queue_max_items=1,
        email_queue_max_age_seconds=0,
        email_queue_max_attempts=0,
        email_queue_retry_base_seconds=0,
        monitors=[
            MonitorConfig(
                window_title_regex="APP",
                phrase_regex="ALERT",
                email=email,
            )
        ],
    )


class _TestNotifier(Notifier):
    __test__ = False

    def set_sender_for_tests(self, sender: EmailSender) -> None:
        for monitor in self._monitors:
            monitor.sender = sender


class FakeSender(EmailSender):
    def __init__(self) -> None:
        self.sent: list[str] = []

    def send(self, message: str) -> None:
        self.sent.append(message)


def test_skips_identical_to_previous_scan(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config()
    status = StatusStore()
    notifier = _TestNotifier(config=config, status=status)

    sender = FakeSender()
    notifier.set_sender_for_tests(sender)

    matches = ["100 ABC", "100 ABC"]

    def _first_matches(_self: WindowTextDetector, _pattern: str) -> list[str]:
        return matches

    monkeypatch.setattr(WindowTextDetector, "find_matches", _first_matches)
    notifier.scan_once()

    # Second scan with identical first match should be skipped.
    def _second_matches(_self: WindowTextDetector, _pattern: str) -> list[str]:
        return ["100 ABC"]

    monkeypatch.setattr(WindowTextDetector, "find_matches", _second_matches)
    notifier.scan_once()

    assert sender.sent == ["100 ABC"]


def test_skips_lower_leading_number(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config()
    status = StatusStore()
    notifier = _TestNotifier(config=config, status=status)

    sender = FakeSender()
    notifier.set_sender_for_tests(sender)

    def _first_matches(_self: WindowTextDetector, _pattern: str) -> list[str]:
        return ["200 ALERT"]

    monkeypatch.setattr(WindowTextDetector, "find_matches", _first_matches)
    notifier.scan_once()

    def _second_matches(_self: WindowTextDetector, _pattern: str) -> list[str]:
        return ["150 ALERT"]

    monkeypatch.setattr(WindowTextDetector, "find_matches", _second_matches)
    notifier.scan_once()

    # Lower leading number should be skipped.
    assert sender.sent == ["200 ALERT"]


def test_allows_higher_leading_number(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config()
    status = StatusStore()
    notifier = _TestNotifier(config=config, status=status)

    sender = FakeSender()
    notifier.set_sender_for_tests(sender)

    def _first_matches(_self: WindowTextDetector, _pattern: str) -> list[str]:
        return ["100 ALERT"]

    monkeypatch.setattr(WindowTextDetector, "find_matches", _first_matches)
    notifier.scan_once()

    def _second_matches(_self: WindowTextDetector, _pattern: str) -> list[str]:
        return ["101 ALERT"]

    monkeypatch.setattr(WindowTextDetector, "find_matches", _second_matches)
    notifier.scan_once()

    # Higher leading number must be sent; delta enrichment adds context line.
    assert len(sender.sent) == 2
    assert sender.sent[0] == "100 ALERT"
    assert sender.sent[1].startswith("101 ALERT")
