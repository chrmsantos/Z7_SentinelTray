import json
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

from z7_sentineltray.logging_setup import log_context, sanitize_text, setup_logging


def test_setup_logging_creates_run_log_and_prunes(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    base_log = log_dir / "z7_sentineltray.log"

    existing = []
    for idx in range(6):
        path = log_dir / f"z7_sentineltray_20260101_00000{idx}_123.log"
        path.write_text("old", encoding="utf-8")
        os.utime(path, (1, 1))
        existing.append(path)

    setup_logging(str(base_log), app_version="1.2.3", release_date="2026-01-22")

    logs = sorted(log_dir.glob("z7_sentineltray_*.log"))
    assert len(logs) == 3
    assert any(path not in existing for path in logs)
    assert base_log.exists()
    assert (log_dir / "z7_sentineltray.jsonl").exists()
    json_runs = sorted(log_dir.glob("z7_sentineltray_*.jsonl"))
    assert json_runs
    assert logging.getLogger("PIL").level == logging.WARNING
    assert logging.getLogger("PIL.Image").level == logging.WARNING

    handlers = logging.getLogger().handlers
    assert any(isinstance(handler, RotatingFileHandler) for handler in handlers)

    for handler in logging.getLogger().handlers:
        handler.close()


def test_setup_logging_caps_retention(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    base_log = log_dir / "z7_sentineltray.log"

    for idx in range(8):
        path = log_dir / f"z7_sentineltray_20260101_00001{idx}_123.log"
        path.write_text("old", encoding="utf-8")
        os.utime(path, (1, 1))

    setup_logging(
        str(base_log),
        log_backup_count=12,
        log_run_files_keep=10,
    )

    logs = sorted(log_dir.glob("z7_sentineltray_*.log"))
    assert len(logs) == 3

    handlers = logging.getLogger().handlers
    rotating_handlers = [
        handler for handler in handlers if isinstance(handler, RotatingFileHandler)
    ]
    assert rotating_handlers
    assert rotating_handlers[0].backupCount == 3

    for handler in logging.getLogger().handlers:
        handler.close()


def test_sanitize_text_redacts_sensitive_values() -> None:
    message = (
        "User test@example.com saved to C:\\Users\\bob\\secret.txt "
        "token=abcd1234 phone +55 (11) 98765-4321"
    )
    sanitized = sanitize_text(message)
    assert "test@example.com" not in sanitized
    assert "C:\\Users\\bob\\secret.txt" not in sanitized
    assert "98765" not in sanitized
    assert "token=abcd1234" not in sanitized
    assert "<email>" in sanitized
    assert "<phone>" in sanitized
    assert "token=<redacted>" in sanitized


def test_json_log_contains_context(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    base_log = log_dir / "z7_sentineltray.log"

    setup_logging(str(base_log), app_version="9.9.9", release_date="2026-01-22")
    logger = logging.getLogger("z7_sentineltray.test")
    logger.setLevel(logging.INFO)
    logger.info("test entry", extra={"category": "test"})

    for handler in logging.getLogger().handlers:
        try:
            handler.flush()
        except Exception:
            continue

    json_path = log_dir / "z7_sentineltray.jsonl"
    assert json_path.exists()
    line = json_path.read_text(encoding="utf-8").splitlines()[-1]
    payload = json.loads(line)
    assert payload["category"] == "test"
    assert payload["message"] == "test entry"
    assert payload["app_version"] == "9.9.9"
    assert payload["release_date"] == "2026-01-22"
    assert payload["session_id"]

    for handler in logging.getLogger().handlers:
        handler.close()


def test_json_log_includes_context_and_event(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    base_log = log_dir / "z7_sentineltray.log"

    setup_logging(str(base_log), app_version="9.9.9", release_date="2026-01-22")
    logger = logging.getLogger("z7_sentineltray.test")
    logger.setLevel(logging.INFO)
    with log_context(monitor_index=1, note="test@example.com"):
        logger.info("context entry", extra={"category": "test", "event": "scan_error"})

    for handler in logging.getLogger().handlers:
        try:
            handler.flush()
        except Exception:
            continue

    json_path = log_dir / "z7_sentineltray.jsonl"
    assert json_path.exists()
    line = json_path.read_text(encoding="utf-8").splitlines()[-1]
    payload = json.loads(line)
    assert payload["event"] == "scan_error"
    assert payload["context"]["monitor_index"] == "1"
    assert "<email>" in payload["context"]["note"]

    for handler in logging.getLogger().handlers:
        handler.close()
