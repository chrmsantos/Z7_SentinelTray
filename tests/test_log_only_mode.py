from z7_sentineltray.app import Notifier
from z7_sentineltray.config import AppConfig, EmailConfig, MonitorConfig
from z7_sentineltray.status import StatusStore


def test_log_only_mode_skips_send() -> None:
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
        log_only_mode=True,
        send_repeated_matches=True,
        monitors=[
            MonitorConfig(
                window_title_regex="APP",
                phrase_regex="ALERT",
                email=email,
            )
        ],
    )

    notifier = Notifier(config=config, status=StatusStore())

    calls = {"count": 0}

    class FakeSender:
        def send(self, _message: str) -> None:
            calls["count"] += 1

    notifier._sender = FakeSender()
    notifier._handle_error("error: test")

    assert calls["count"] == 1
