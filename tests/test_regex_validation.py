from pathlib import Path

import pytest

from z7_sentineltray.config import load_config


def test_invalid_regex_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "monitors:",
                "  - window_title_regex: '('",
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
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="window_title_regex invalid regex"):
        load_config(str(config_path))
