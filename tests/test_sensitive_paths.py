from pathlib import Path

import pytest

from z7_sentineltray.config import get_user_data_dir, get_user_log_dir, load_config


def test_sensitive_paths_forced_to_user_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("USERPROFILE", str(tmp_path))

    other_root = tmp_path / "other"
    other_root.mkdir()

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
                f"state_file: '{other_root / 'state.json'}'",
                f"log_file: '{other_root / 'logs' / 'z7_sentineltray.log'}'",
                "log_level: 'INFO'",
                "log_console_level: 'WARNING'",
                "log_console_enabled: true",
                "log_max_bytes: 5000000",
                "log_backup_count: 3",
                "log_run_files_keep: 3",
                f"telemetry_file: '{other_root / 'telemetry.json'}'",
                "allow_window_restore: true",
                "log_only_mode: false",
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(str(config_path))

    base = get_user_data_dir()
    log_root = get_user_log_dir()
    assert config.state_file == str(base / "state.json")
    assert config.log_file == str(log_root / "z7_sentineltray.log")
    assert config.telemetry_file == str(log_root / "telemetry.json")
