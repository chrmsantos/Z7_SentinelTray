from pathlib import Path

import pytest

from z7_sentineltray.config import get_user_data_dir, get_user_log_dir, load_config
from z7_sentineltray.dpapi_utils import save_secret


def test_load_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    config_path = Path(__file__).parent / "data" / "config.yaml"
    config = load_config(str(config_path))

    assert config.monitors[0].window_title_regex == "App\\.Monitor\\.Desktop"
    assert config.monitors[0].phrase_regex == "ALERT"
    assert config.poll_interval_seconds == 180
    assert config.healthcheck_interval_seconds == 900
    assert config.error_backoff_base_seconds == 5
    assert config.error_backoff_max_seconds == 300
    assert config.debounce_seconds == 600
    log_root = get_user_log_dir()
    assert config.log_file == str(log_root / "z7_sentineltray.log")
    assert config.log_level == "INFO"
    assert config.log_console_level == "WARNING"
    assert config.log_console_enabled is True
    assert config.log_max_bytes == 5000000
    assert config.log_backup_count == 3
    assert config.log_run_files_keep == 3
    assert config.telemetry_file == str(log_root / "telemetry.json")
    assert config.config_version == 1


def test_log_retention_is_capped(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    config_path = tmp_path / "config.yaml"
    base_config = (Path(__file__).parent / "data" / "config.yaml").read_text(encoding="utf-8")
    updated = base_config.replace("log_backup_count: 3", "log_backup_count: 12")
    updated = updated.replace("log_run_files_keep: 3", "log_run_files_keep: 9")
    config_path.write_text(updated, encoding="utf-8")

    config = load_config(str(config_path))

    assert config.log_backup_count == 3
    assert config.log_run_files_keep == 3


def test_load_config_with_monitors(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "monitors:",
                "  - window_title_regex: 'APP1'",
                "    phrase_regex: 'ALERT1'",
                "    email:",
                "      smtp_host: 'smtp.local'",
                "      smtp_port: 587",
                "      smtp_username: 'smtp-user'",
                "      smtp_password: ''",
                "      from_address: 'alerts1@example.com'",
                "      to_addresses: ['ops1@example.com']",
                "      use_tls: true",
                "      timeout_seconds: 10",
                "      subject: 'Z7_SentinelTray Notification'",
                "      retry_attempts: 0",
                "      retry_backoff_seconds: 0",
                "  - window_title_regex: 'APP2'",
                "    phrase_regex: 'ALERT2'",
                "    email:",
                "      smtp_host: 'smtp.local'",
                "      smtp_port: 587",
                "      smtp_username: 'smtp-user'",
                "      smtp_password: ''",
                "      from_address: 'alerts2@example.com'",
                "      to_addresses: ['ops2@example.com']",
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
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(str(config_path))

    assert len(config.monitors) == 2
    assert config.monitors[0].window_title_regex == "APP1"
    assert config.monitors[1].window_title_regex == "APP2"


def test_smtp_password_dpapi_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.delenv("Z7_SENTINELTRAY_SMTP_PASSWORD", raising=False)
    monkeypatch.delenv("Z7_SENTINELTRAY_SMTP_PASSWORD_1", raising=False)
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

    secret_path = get_user_data_dir() / "smtp_password_1.dpapi"
    save_secret(secret_path, "secret")

    config = load_config(str(config_path))
    assert config.monitors[0].email.smtp_password == "secret"


def test_smtp_default_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.delenv("Z7_SENTINELTRAY_SMTP_PASSWORD", raising=False)
    monkeypatch.delenv("Z7_SENTINELTRAY_SMTP_PASSWORD_1", raising=False)
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
                "      smtp_username: ''",
                "      smtp_password: ''",
                "      from_address: ''",
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
    assert config.monitors[0].email.smtp_username == "sentineltray.google.com"
    assert config.monitors[0].email.from_address == "sentineltray.google.com"
    assert config.monitors[0].email.smtp_password == "udco pjfs keaw ukts"

