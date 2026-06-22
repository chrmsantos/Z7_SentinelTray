from z7_sentineltray.app import Notifier
from z7_sentineltray.config import AppConfig, EmailConfig, MonitorConfig
from z7_sentineltray.status import StatusStore


def _make_email() -> EmailConfig:
    return EmailConfig(
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


def _make_config(**overrides) -> AppConfig:
    defaults = dict(
        poll_interval_seconds=1,
        healthcheck_interval_seconds=3600,
        error_backoff_base_seconds=5,
        error_backoff_max_seconds=300,
        debounce_seconds=600,
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
        monitors=[
            MonitorConfig(
                window_title_regex="APP",
                phrase_regex="ALERT",
                email=_make_email(),
            )
        ],
    )
    defaults.update(overrides)
    return AppConfig(**defaults)


def test_send_healthcheck_updates_status_and_sends() -> None:
    config = _make_config(healthcheck_send_on_error_only=False)
    status = StatusStore()
    notifier = Notifier(config=config, status=status)

    sent: list[str] = []

    class FakeSender:
        def send(self, message: str) -> None:
            sent.append(message)

    notifier._sender = FakeSender()
    status.set_last_scan("t1")
    status.set_last_send("s1")
    status.set_last_error("")

    notifier._send_healthcheck()

    snapshot = status.snapshot()
    assert len(sent) == 1, "healthcheck should produce one email"
    assert "status:" in sent[0].lower()
    assert snapshot.last_send != "s1", "last_send should be updated by healthcheck"
    assert snapshot.last_healthcheck
    assert snapshot.uptime_seconds >= 0


def test_send_healthcheck_skips_send_when_no_error_and_error_only_mode() -> None:
    config = _make_config(healthcheck_send_on_error_only=True)
    status = StatusStore()
    notifier = Notifier(config=config, status=status)

    sent: list[str] = []

    class FakeSender:
        def send(self, message: str) -> None:
            sent.append(message)

    notifier._sender = FakeSender()
    status.set_last_send("s1")
    status.set_last_error("")

    notifier._send_healthcheck()

    snapshot = status.snapshot()
    assert len(sent) == 0, "no email should be sent when there is no error"
    assert snapshot.last_send == "s1", "last_send should not be updated when skipped"
    assert snapshot.last_healthcheck, "last_healthcheck should still be updated"


def test_send_healthcheck_sends_when_error_present_and_error_only_mode() -> None:
    config = _make_config(healthcheck_send_on_error_only=True)
    status = StatusStore()
    notifier = Notifier(config=config, status=status)

    sent: list[str] = []

    class FakeSender:
        def send(self, message: str) -> None:
            sent.append(message)

    notifier._sender = FakeSender()
    status.set_last_send("s1")
    status.set_last_error("erro: falha ao varrer janela")

    notifier._send_healthcheck()

    snapshot = status.snapshot()
    assert len(sent) == 1, "email should be sent when there is an active error"
    assert "status:" in sent[0].lower()
    assert snapshot.last_healthcheck

