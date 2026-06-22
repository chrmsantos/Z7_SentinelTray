from pathlib import Path

import pytest

from z7_sentineltray.config import get_user_log_dir, load_config


def test_invalid_poll_interval_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "monitors:",
                "  - window_title_regex: 'APP'",
                "    phrase_regex: 'ALERT'",
                "    email:",
                "      smtp_host: ''",
                "      smtp_port: 587",
                "      smtp_username: ''",
                "      smtp_password: ''",
                "      from_address: ''",
                "      to_addresses: []",
                "      use_tls: true",
                "      timeout_seconds: 10",
                "      subject: 'Z7_SentinelTray Notification'",
                "      retry_attempts: 0",
                "      retry_backoff_seconds: 0",
                "poll_interval_seconds: 0",
                "healthcheck_interval_seconds: 60",
                "error_backoff_base_seconds: 5",
                "error_backoff_max_seconds: 10",
                "debounce_seconds: 0",
                "max_history: 10",
                "state_file: 'state.json'",
                "log_file: 'logs/z7_sentineltray.log'",
                "log_level: 'INFO'",
                "log_console_level: 'WARNING'",
                "log_console_enabled: true",
                "log_max_bytes: 5000000",
                "log_backup_count: 3",
                "log_run_files_keep: 3",
                "telemetry_file: 'logs/telemetry.json'",
                "allow_window_restore: true",
                "log_only_mode: false",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="poll_interval_seconds"):
        load_config(str(config_path))


def test_log_paths_are_rehomed_to_user_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    log_root = get_user_log_dir()
    outside_log = log_root.parent / "other" / "z7_sentineltray.log"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "monitors:",
                "  - window_title_regex: 'APP'",
                "    phrase_regex: 'ALERT'",
                "    email:",
                "      smtp_host: 'smtp.local'",
                "      smtp_port: 587",
                "      smtp_username: 'smtp-user'",
                "      smtp_password: ''",
                "      from_address: 'alerts@example.com'",
                "      to_addresses: ['ops@example.com']",
                "      use_tls: true",
                "      timeout_seconds: 10",
                "      subject: 'Z7_SentinelTray Notification'",
                "      retry_attempts: 0",
                "      retry_backoff_seconds: 0",
                "poll_interval_seconds: 1",
                "healthcheck_interval_seconds: 60",
                "error_backoff_base_seconds: 5",
                "error_backoff_max_seconds: 10",
                "debounce_seconds: 0",
                "max_history: 10",
                "state_file: 'state.json'",
                f"log_file: '{outside_log}'",
                "log_level: 'INFO'",
                "log_console_level: 'WARNING'",
                "log_console_enabled: true",
                "log_max_bytes: 5000000",
                "log_backup_count: 3",
                "log_run_files_keep: 3",
                "telemetry_file: 'logs/telemetry.json'",
                "allow_window_restore: true",
                "log_only_mode: false",
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(str(config_path))

    assert config.log_file == str(log_root / "z7_sentineltray.log")


def test_invalid_config_version_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "monitors:",
                "  - window_title_regex: 'APP'",
                "    phrase_regex: 'ALERT'",
                "    email:",
                "      smtp_host: ''",
                "      smtp_port: 587",
                "      smtp_username: ''",
                "      smtp_password: ''",
                "      from_address: ''",
                "      to_addresses: []",
                "      use_tls: true",
                "      timeout_seconds: 10",
                "      subject: 'Z7_SentinelTray Notification'",
                "      retry_attempts: 0",
                "      retry_backoff_seconds: 0",
                "poll_interval_seconds: 1",
                "healthcheck_interval_seconds: 60",
                "error_backoff_base_seconds: 5",
                "error_backoff_max_seconds: 10",
                "debounce_seconds: 0",
                "max_history: 10",
                "state_file: 'state.json'",
                "log_file: 'logs/z7_sentineltray.log'",
                "log_level: 'INFO'",
                "log_console_level: 'WARNING'",
                "log_console_enabled: true",
                "log_max_bytes: 5000000",
                "log_backup_count: 3",
                "log_run_files_keep: 3",
                "telemetry_file: 'logs/telemetry.json'",
                "allow_window_restore: true",
                "log_only_mode: false",
                "config_version: 0",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="config_version"):
        load_config(str(config_path))


def test_smtp_password_allows_config_value(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "monitors:",
                "  - window_title_regex: 'APP'",
                "    phrase_regex: 'ALERT'",
                "    email:",
                "      smtp_host: 'smtp.local'",
                "      smtp_port: 587",
                "      smtp_username: 'smtp-user'",
                "      smtp_password: 'secret'",
                "      from_address: 'alerts@example.com'",
                "      to_addresses: ['ops@example.com']",
                "      use_tls: true",
                "      timeout_seconds: 10",
                "      subject: 'Z7_SentinelTray Notification'",
                "      retry_attempts: 0",
                "      retry_backoff_seconds: 0",
                "poll_interval_seconds: 60",
                "healthcheck_interval_seconds: 60",
                "error_backoff_base_seconds: 5",
                "error_backoff_max_seconds: 10",
                "debounce_seconds: 0",
                "max_history: 10",
                "state_file: 'state.json'",
                "log_file: 'logs/z7_sentineltray.log'",
                "log_level: 'INFO'",
                "log_console_level: 'WARNING'",
                "log_console_enabled: true",
                "log_max_bytes: 5000000",
                "log_backup_count: 3",
                "log_run_files_keep: 3",
                "telemetry_file: 'logs/telemetry.json'",
                "allow_window_restore: true",
                "log_only_mode: false",
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(str(config_path))
    assert config.monitors[0].email.smtp_password == "secret"


def test_smtp_password_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("Z7_SENTINELTRAY_SMTP_PASSWORD", "secret")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "monitors:",
                "  - window_title_regex: 'APP'",
                "    phrase_regex: 'ALERT'",
                "    email:",
                "      smtp_host: 'smtp.local'",
                "      smtp_port: 587",
                "      smtp_username: 'smtp-user'",
                "      smtp_password: ''",
                "      from_address: 'alerts@example.com'",
                "      to_addresses: ['ops@example.com']",
                "      use_tls: true",
                "      timeout_seconds: 10",
                "      subject: 'Z7_SentinelTray Notification'",
                "      retry_attempts: 0",
                "      retry_backoff_seconds: 0",
                "poll_interval_seconds: 60",
                "healthcheck_interval_seconds: 60",
                "error_backoff_base_seconds: 5",
                "error_backoff_max_seconds: 10",
                "debounce_seconds: 0",
                "max_history: 10",
                "state_file: 'state.json'",
                "log_file: 'logs/z7_sentineltray.log'",
                "log_level: 'INFO'",
                "log_console_level: 'WARNING'",
                "log_console_enabled: true",
                "log_max_bytes: 5000000",
                "log_backup_count: 3",
                "log_run_files_keep: 3",
                "telemetry_file: 'logs/telemetry.json'",
                "allow_window_restore: true",
                "log_only_mode: false",
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(str(config_path))
    assert config.monitors[0].email.smtp_password == "secret"
