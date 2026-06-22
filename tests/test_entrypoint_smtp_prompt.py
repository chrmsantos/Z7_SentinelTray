from __future__ import annotations

import pytest

from z7_sentineltray import entrypoint
from z7_sentineltray.config import AppConfig, EmailConfig, MonitorConfig


def _make_config(username: str) -> AppConfig:
    email = EmailConfig(
        smtp_host="smtp.local",
        smtp_port=587,
        smtp_username=username,
        smtp_password="",
        from_address="alerts@example.com",
        to_addresses=["ops@example.com"],
        use_tls=True,
        timeout_seconds=10,
        subject="Z7_SentinelTray",
        retry_attempts=1,
        retry_backoff_seconds=1,
    )
    monitor = MonitorConfig(
        window_title_regex="APP",
        phrase_regex="ALERT",
        email=email,
    )
    return AppConfig(
        poll_interval_seconds=180,
        healthcheck_interval_seconds=900,
        error_backoff_base_seconds=5,
        error_backoff_max_seconds=300,
        debounce_seconds=60,
        max_history=50,
        state_file="state.json",
        log_file="logs/z7_sentineltray.log",
        log_level="INFO",
        log_console_level="WARNING",
        log_console_enabled=True,
        log_max_bytes=5_000_000,
        log_backup_count=3,
        log_run_files_keep=3,
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
        email_queue_max_items=500,
        email_queue_max_age_seconds=86400,
        email_queue_max_attempts=10,
        email_queue_retry_base_seconds=30,
        monitors=[monitor],
        config_version=1,
    )


def test_missing_smtp_passwords_requires_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("Z7_SENTINELTRAY_SMTP_PASSWORD", raising=False)
    monkeypatch.delenv("Z7_SENTINELTRAY_SMTP_PASSWORD_1", raising=False)
    config = _make_config("smtp-user")

    missing = entrypoint._missing_smtp_passwords(config)

    assert missing == [(1, "smtp-user")]


def test_prompt_smtp_password_sets_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("Z7_SENTINELTRAY_SMTP_PASSWORD", raising=False)
    monkeypatch.delenv("Z7_SENTINELTRAY_SMTP_PASSWORD_1", raising=False)

    monkeypatch.setattr(
        "z7_sentineltray.gui_app.prompt_smtp_password_gui", lambda _user, _idx: "secret"
    )

    entrypoint._prompt_smtp_passwords([(1, "smtp-user")])

    assert entrypoint.os.environ["Z7_SENTINELTRAY_SMTP_PASSWORD_1"] == "secret"


def test_missing_passwords_skips_when_global_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("Z7_SENTINELTRAY_SMTP_PASSWORD", "global")
    config = _make_config("smtp-user")

    missing = entrypoint._missing_smtp_passwords(config)

    assert missing == []


def test_missing_passwords_skips_empty_username(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("Z7_SENTINELTRAY_SMTP_PASSWORD", raising=False)
    config = _make_config("")

    missing = entrypoint._missing_smtp_passwords(config)

    assert missing == []


def test_missing_passwords_skips_when_config_has_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("Z7_SENTINELTRAY_SMTP_PASSWORD", raising=False)
    config = _make_config("smtp-user")
    config = config.__class__(
        **{
            **config.__dict__,
            "monitors": [
                config.monitors[0].__class__(
                    window_title_regex=config.monitors[0].window_title_regex,
                    phrase_regex=config.monitors[0].phrase_regex,
                    email=config.monitors[0].email.__class__(
                        **{
                            **config.monitors[0].email.__dict__,
                            "smtp_password": "secret",
                        }
                    ),
                )
            ],
        }
    )

    missing = entrypoint._missing_smtp_passwords(config)

    assert missing == []
