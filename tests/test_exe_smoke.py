"""Smoke tests for the built Z7_SentinelTray.exe.

These tests launch the actual compiled executable and verify:
1. --version exits cleanly with code 0.
2. A full startup run with a dry-run config produces no CRITICAL/ERROR log
   entries (other than expected window-not-found notices).
3. Startup log markers are present (logging initialized, started).

Run with: pytest tests/test_exe_smoke.py -v
"""

from __future__ import annotations

import os
import subprocess
import textwrap
import time
from contextlib import suppress
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

EXE_PATH = Path(__file__).resolve().parents[1] / "dist" / "Z7_SentinelTray.exe"

_MINIMAL_CONFIG = textwrap.dedent("""\
monitors:
- window_title_regex: 'Z7_SentinelTray_SmokeTest_DoesNotExist'
  phrase_regex: 'SMOKETEST'
  email:
    smtp_host: '127.0.0.1'
    smtp_port: 2525
    smtp_username: 'test@example.com'
    smtp_password: 'test'
    from_address: 'test@example.com'
    to_addresses: ['test@example.com']
    use_tls: false
    timeout_seconds: 5
    subject: 'SmokeTest'
    retry_attempts: 0
    retry_backoff_seconds: 1

poll_interval_seconds: 2
healthcheck_interval_seconds: 3600
error_backoff_base_seconds: 1
error_backoff_max_seconds: 5
debounce_seconds: 0
max_history: 10

state_file: state.json
log_file: logs/z7_sentineltray.log
log_level: DEBUG
log_console_level: WARNING
log_console_enabled: false
log_max_bytes: 1000000
log_backup_count: 1
log_run_files_keep: 3
telemetry_file: logs/telemetry.json

allow_window_restore: false
log_only_mode: true
send_repeated_matches: true
min_repeat_seconds: 0
error_notification_cooldown_seconds: 0

window_error_backoff_base_seconds: 1
window_error_backoff_max_seconds: 5
window_error_circuit_threshold: 10
window_error_circuit_seconds: 10

email_queue_file: logs/email_queue.json
email_queue_max_items: 10
email_queue_max_age_seconds: 3600
email_queue_max_attempts: 1
email_queue_retry_base_seconds: 5

pause_on_user_active: false
pause_idle_threshold_seconds: 60
""")


def _exe_available() -> bool:
    return EXE_PATH.exists()


def _setup_root(tmp_path: Path) -> Path:
    """Create a minimal project root with working config inside tmp_path."""
    root = tmp_path / "z7_sentineltray_root"
    config_dir = root / "config"
    log_dir = config_dir / "logs"
    config_dir.mkdir(parents=True)
    log_dir.mkdir(parents=True)
    (config_dir / "config.local.yaml").write_text(_MINIMAL_CONFIG, encoding="utf-8")
    return root


def _collect_run_logs(root: Path) -> list[Path]:
    """Return all run-specific log files produced under config/logs."""
    log_dir = root / "config" / "logs"
    return sorted(log_dir.glob("z7_sentineltray_*.log"))


def _parse_log_lines(log_files: list[Path]) -> list[dict]:
    """Parse plain-text log lines into dicts with at least level and message."""
    entries: list[dict] = []
    for path in log_files:
        try:
            for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
                raw = raw.strip()
                if not raw:
                    continue
                parts = raw.split(None, 2)
                if len(parts) >= 3:
                    # Format: DATE TIME LEVEL ...
                    entries.append({"level": parts[2] if len(parts) > 2 else "?", "raw": raw})
        except OSError:
            continue
    return entries


def _kill_tree(pid: int) -> None:
    """Kill a process and all its children using taskkill /F /T."""
    with suppress(Exception):
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True,
            timeout=10,
        )


def _run_exe(
    root: Path,
    *args: str,
    timeout: int = 8,
    kill_after: float | None = None,
) -> subprocess.CompletedProcess[str]:
    """
    Launch Z7_SentinelTray.exe with Z7_SENTINELTRAY_ROOT pointing to *root*.

    If kill_after is set, the process is given that many seconds to start,
    then the entire process tree is killed (including children that may have
    inherited pipe handles), and the result is collected.
    """
    env = {
        **os.environ,
        "Z7_SENTINELTRAY_ROOT": str(root),
        "Z7_SENTINELTRAY_DATA_DIR": str(root / "config"),
    }
    if kill_after is not None:
        proc = subprocess.Popen(
            [str(EXE_PATH), *args],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        # Poll dynamically for up to 45 seconds waiting for the run log to be created.
        # This gracefully handles Windows Defender scanning overhead during cold starts.
        poll_limit = max(45.0, kill_after)
        poll_interval = 0.5
        elapsed = 0.0
        while elapsed < poll_limit:
            if _collect_run_logs(root):
                break
            time.sleep(poll_interval)
            elapsed += poll_interval
        # Allow an extra 2 seconds for startup log markers to be written stably
        time.sleep(2.0)
        # Kill the whole process tree so child processes don't keep pipes open.
        _kill_tree(proc.pid)
        # Drain remaining pipe data with a hard timeout.
        try:
            stdout_bytes, stderr_bytes = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                stdout_bytes, stderr_bytes = proc.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                stdout_bytes, stderr_bytes = b"", b""
        return subprocess.CompletedProcess(
            args=[str(EXE_PATH), *args],
            returncode=proc.returncode if proc.returncode is not None else -1,
            stdout=stdout_bytes.decode("utf-8", errors="replace"),
            stderr=stderr_bytes.decode("utf-8", errors="replace"),
        )
    result = subprocess.run(
        [str(EXE_PATH), *args],
        env=env,
        capture_output=True,
        timeout=timeout,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return subprocess.CompletedProcess(
        args=result.args,
        returncode=result.returncode,
        stdout=result.stdout.decode("utf-8", errors="replace"),
        stderr=result.stderr.decode("utf-8", errors="replace"),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _exe_available(), reason=f"Executable not found: {EXE_PATH}")
def test_exe_version_flag(tmp_path: Path) -> None:
    """--version must exit 0 and print the version string."""
    root = _setup_root(tmp_path)
    result = _run_exe(root, "--version", timeout=30)
    assert result.returncode == 0, (
        f"--version exited with code {result.returncode}\n"
        f"stdout: {result.stdout!r}\n"
        f"stderr: {result.stderr!r}"
    )
    combined = result.stdout + result.stderr
    assert "Z7_SentinelTray" in combined, (
        f"Expected 'Z7_SentinelTray' in output, got:\n{combined!r}"
    )


@pytest.mark.skipif(not _exe_available(), reason=f"Executable not found: {EXE_PATH}")
def test_exe_help_flag(tmp_path: Path) -> None:
    """--help must exit 0."""
    root = _setup_root(tmp_path)
    result = _run_exe(root, "--help", timeout=30)
    assert result.returncode == 0, (
        f"--help exited with code {result.returncode}\n"
        f"stdout: {result.stdout!r}\n"
        f"stderr: {result.stderr!r}"
    )


@pytest.mark.skipif(not _exe_available(), reason=f"Executable not found: {EXE_PATH}")
def test_exe_unknown_flag_exits_nonzero(tmp_path: Path) -> None:
    """Unknown flags must cause a non-zero exit."""
    root = _setup_root(tmp_path)
    result = _run_exe(root, "--unknown-flag", timeout=30)
    assert result.returncode != 0, (
        f"Expected non-zero exit for unknown flag, got {result.returncode}"
    )


@pytest.mark.skipif(not _exe_available(), reason=f"Executable not found: {EXE_PATH}")
def test_exe_startup_creates_log_files(tmp_path: Path) -> None:
    """Running the exe for a few seconds must create log files."""
    root = _setup_root(tmp_path)
    _run_exe(root, kill_after=20.0)
    log_files = _collect_run_logs(root)
    assert log_files, (
        "No run log files found after startup.\n"
        f"Expected logs under: {root / 'config' / 'logs'}\n"
        "Contents: "
        + str(
            list((root / "config" / "logs").iterdir())
            if (root / "config" / "logs").exists()
            else []
        )
    )


@pytest.mark.skipif(not _exe_available(), reason=f"Executable not found: {EXE_PATH}")
def test_exe_startup_log_has_initialized_marker(tmp_path: Path) -> None:
    """The log must contain 'Logging initialized' from the startup sequence."""
    root = _setup_root(tmp_path)
    _run_exe(root, kill_after=20.0)
    log_files = _collect_run_logs(root)
    assert log_files, f"No log files found under {root / 'config' / 'logs'}"
    all_text = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in log_files)
    assert "Logging initialized" in all_text, (
        "Expected 'Logging initialized' in logs.\nLog content:\n" + all_text[:2000]
    )


@pytest.mark.skipif(not _exe_available(), reason=f"Executable not found: {EXE_PATH}")
def test_exe_startup_log_has_started_marker(tmp_path: Path) -> None:
    """The log must contain the 'Z7_SentinelTray started' marker."""
    root = _setup_root(tmp_path)
    _run_exe(root, kill_after=20.0)
    log_files = _collect_run_logs(root)
    assert log_files, f"No log files found under {root / 'config' / 'logs'}"
    all_text = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in log_files)
    assert "Z7_SentinelTray started" in all_text, (
        "Expected 'Z7_SentinelTray started' in logs.\nLog content:\n" + all_text[:2000]
    )


@pytest.mark.skipif(not _exe_available(), reason=f"Executable not found: {EXE_PATH}")
def test_exe_startup_no_critical_errors(tmp_path: Path) -> None:
    """There must be no CRITICAL log entries after startup."""
    root = _setup_root(tmp_path)
    _run_exe(root, kill_after=20.0)
    log_files = _collect_run_logs(root)
    entries = _parse_log_lines(log_files)
    critical = [e["raw"] for e in entries if "CRITICAL" in e["level"]]
    assert not critical, f"Found {len(critical)} CRITICAL log entries:\n" + "\n".join(critical[:10])


@pytest.mark.skipif(not _exe_available(), reason=f"Executable not found: {EXE_PATH}")
def test_exe_startup_no_unexpected_errors(tmp_path: Path) -> None:
    """ERROR entries must only be startup-related, not recurring loop errors."""
    root = _setup_root(tmp_path)
    _run_exe(root, kill_after=20.0)
    log_files = _collect_run_logs(root)
    entries = _parse_log_lines(log_files)
    error_lines = [e["raw"] for e in entries if e["level"].startswith("ERROR")]
    # Filter out known-benign patterns (telemetry write race on shutdown, etc.)
    _benign_re = [
        "Telemetry write failed",  # race on shutdown / permission
        "State persistence failed",  # race on shutdown
    ]
    unexpected = [line for line in error_lines if not any(pat in line for pat in _benign_re)]
    assert not unexpected, f"Found {len(unexpected)} unexpected ERROR log entries:\n" + "\n".join(
        unexpected[:10]
    )


@pytest.mark.skipif(not _exe_available(), reason=f"Executable not found: {EXE_PATH}")
def test_exe_disk_check_no_failure(tmp_path: Path) -> None:
    """The disk check must not produce 'Disk check failed' errors."""
    root = _setup_root(tmp_path)
    _run_exe(root, kill_after=20.0)
    log_files = _collect_run_logs(root)
    all_text = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in log_files)
    assert "Disk check failed" not in all_text, (
        "Disk check failed found in logs — _config attribute bug may have returned.\n"
        "Log content:\n" + all_text[:3000]
    )
