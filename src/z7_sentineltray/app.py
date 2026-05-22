"""Core monitoring engine: Notifier, MonitorRuntime, and the main run loop."""

from __future__ import annotations

import ctypes
import hashlib
import importlib.metadata
import json
import logging
import re
import shutil
import socket
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Thread
from typing import Any, cast
from uuid import uuid4

from . import __release_date__, __version_label__
from .config import AppConfig, MonitorConfig, get_project_root
from .detector import WindowTextDetector, WindowUnavailableError
from .email_sender import (
    EmailAuthError,
    EmailQueued,
    EmailSender,
    QueueingEmailSender,
    build_sender,
)
from .idle_utils import get_idle_seconds
from .io_utils import read_json_safe
from .logging_setup import log_context, sanitize_text, scan_context, setup_logging
from .scan_utils import dedupe_items, filter_debounce, filter_min_repeat
from .status import StatusStore, format_status
from .telemetry import JsonWriter, atomic_write_text

LOGGER = logging.getLogger(__name__)
EMAIL_DISABLED_LOG_COOLDOWN_SECONDS = 300


@dataclass
class MonitorRuntime:
    """Runtime state for a single configured monitor."""

    key: str
    config: MonitorConfig
    detector: WindowTextDetector
    sender: EmailSender
    last_sent: dict[str, datetime] = field(default_factory=lambda: cast(dict[str, datetime], {}))
    email_disabled: bool = False
    last_email_disabled_log_at: float = 0.0
    failure_count: int = 0
    breaker_until: float = 0.0
    last_window_ok_at: str = ""
    last_window_error_at: str = ""
    last_error_notification_at: float = 0.0
    last_send_queued: bool = False
    last_scan_text: str = ""
    last_scan_number: int | None = None


def _apply_execution_state(prevent_sleep: bool) -> bool:
    try:
        kernel32 = ctypes.windll.kernel32
    except Exception:
        return False
    try:
        continuous = 0x80000000
        flags = continuous | 1 | 2 if prevent_sleep else continuous
        return bool(kernel32.SetThreadExecutionState(flags))
    except Exception:
        return False


def _load_state(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    data = read_json_safe(path, default=[], context="state file")
    if isinstance(data, list):
        items = cast(list[object], data)
        if all(isinstance(item, str) for item in items):
            now = _now_iso()
            return [{"text": str(item), "sent_at": now} for item in items]
        normalized_items: list[dict[str, str]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            typed_item = cast(dict[str, object], item)
            text = typed_item.get("text")
            sent_at = typed_item.get("sent_at")
            if isinstance(text, str) and isinstance(sent_at, str):
                normalized_items.append({"text": text, "sent_at": sent_at})
        return normalized_items
    return []


def _save_state(path: Path, items: list[dict[str, str]]) -> None:
    atomic_write_text(
        path,
        json.dumps(items, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _normalize(text: str) -> str:
    return " ".join(text.split())


def _now_iso() -> str:
    return datetime.now(UTC).astimezone().replace(microsecond=0).isoformat()


def _to_ascii(text: str) -> str:
    return text.encode("ascii", "backslashreplace").decode("ascii")


def _summarize_text(text: str) -> str:
    cleaned = _normalize(text or "")
    if not cleaned:
        return ""
    digest = hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:12]
    return f"text(len={len(cleaned)}, sha={digest})"


def _hash_value(value: str) -> str:
    cleaned = _normalize(value or "")
    if not cleaned:
        return ""
    return hashlib.sha256(cleaned.encode("utf-8")).hexdigest()


def _safe_status_text(text: str) -> str:
    if not text:
        return ""
    return sanitize_text(_to_ascii(text))


def _leading_number(text: str) -> int | None:
    if not text:
        return None
    match = re.match(r"\s*(\d+)", text)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _build_alert_message(text: str, previous_number: int | None) -> str:
    """Enrich alert text with a change indicator relative to the previous scan's count.

    When a leading counter is detected (e.g. "10 PROPOSITURAS NÃO RECEBIDAS"),
    the delta versus *previous_number* is appended so the recipient immediately
    knows how many new items arrived since the last notification.
    """
    current_number = _leading_number(text)
    if current_number is None or previous_number is None:
        return text
    delta = current_number - previous_number
    if delta == 0:
        return text
    delta_label = f"+{delta}" if delta > 0 else str(delta)
    return f"{text}\nVariação desde o último scan: {delta_label}"


def _get_version() -> str:
    try:
        return importlib.metadata.version("z7_sentineltray")
    except importlib.metadata.PackageNotFoundError:
        return __version_label__


def _get_release_date() -> str:
    return __release_date__


def _get_commit_hash() -> str:
    try:
        base = get_project_root()
        head_path = base / ".git" / "HEAD"
        if not head_path.exists():
            return ""
        ref = head_path.read_text(encoding="utf-8").strip()
        if not ref.startswith("ref:"):
            return ref  # detached HEAD — already a commit hash
        ref_name = ref.replace("ref:", "").strip()
        ref_path = base / ".git" / ref_name
        if ref_path.exists():
            return ref_path.read_text(encoding="utf-8").strip()
        # Fallback: check packed-refs
        packed = base / ".git" / "packed-refs"
        if packed.exists():
            for line in packed.read_text(encoding="utf-8").splitlines():
                if line.startswith("#"):
                    continue
                parts = line.split()
                if len(parts) == 2 and parts[1] == ref_name:  # noqa: PLR2004
                    return parts[0]
        return ""
    except Exception:
        return ""


def _check_smtp_health(config: AppConfig) -> None:
    if not config.monitors:
        return

    def _check() -> None:
        try:
            for monitor_cfg in config.monitors:
                email = monitor_cfg.email
                host = email.smtp_host
                port = email.smtp_port
                if not host or not port:
                    continue
                try:
                    with socket.create_connection((host, int(port)), timeout=10):
                        pass
                except OSError as exc:
                    LOGGER.warning(
                        "SMTP healthcheck failed for %s:%s: %s",
                        host,
                        port,
                        exc,
                        extra={"category": "send"},
                    )
        except Exception:
            LOGGER.debug("SMTP healthcheck thread failed unexpectedly", exc_info=True)

    t = Thread(target=_check, daemon=True, name="smtp-health-check")
    t.start()


@dataclass
class Notifier:
    """Orchestrates monitors, email delivery, and loop lifecycle."""

    config: AppConfig
    status: StatusStore

    def __post_init__(self) -> None:
        self._monitors = self._build_monitors()
        self._state_path = Path(self.config.state_file)
        self._history = _load_state(self._state_path)
        for monitor in self._monitors:
            monitor.last_sent = self._build_last_sent_map(self._history, monitor.key)
        self._started_at = datetime.now(UTC)
        self._next_healthcheck = time.monotonic() + self.config.healthcheck_interval_seconds
        self._next_queue_drain = time.monotonic() + 30
        self._telemetry = JsonWriter(Path(self.config.telemetry_file))
        self._app_version = _get_version()
        self._release_date = _get_release_date()
        self._commit_hash = ""
        self._telemetry_write_errors = 0
        self._state_write_errors = 0
        self._last_scan_error = False
        self._last_scan_had_match = False
        self._last_no_match_test_at: float = 0.0
        self._last_error_notification_at = 0.0
        self._queue_stats: dict[str, int] = {
            "queued": 0,
            "sent": 0,
            "failed": 0,
            "deferred": 0,
            "oldest_age_seconds": 0,
        }
        self._sender: EmailSender | None = None
        self._commit_hash_ready: Event = Event()

        def _fetch_commit_hash() -> None:
            try:
                self._commit_hash = _get_commit_hash()
            except Exception:
                LOGGER.debug("Failed to fetch commit hash", exc_info=True)
            finally:
                self._commit_hash_ready.set()

        Thread(target=_fetch_commit_hash, daemon=True, name="commit-hash").start()
        _check_smtp_health(self.config)

    def _reset_components(self) -> None:
        for monitor in self._monitors:
            monitor.detector = WindowTextDetector(
                monitor.config.window_title_regex,
                allow_window_restore=self.config.allow_window_restore,
                log_throttle_seconds=60,
            )
            monitor.sender = build_sender(
                monitor.config.email,
                queue_path=self._queue_path_for_monitor(monitor.key, len(self._monitors)),
                queue_max_items=self.config.email_queue_max_items,
                queue_max_age_seconds=self.config.email_queue_max_age_seconds,
                queue_max_attempts=self.config.email_queue_max_attempts,
                queue_retry_base_seconds=self.config.email_queue_retry_base_seconds,
            )
            monitor.email_disabled = False
            monitor.failure_count = 0
            monitor.breaker_until = 0.0

    def _build_last_sent_map(
        self, history: list[dict[str, str]], monitor_key: str | None
    ) -> dict[str, datetime]:
        last_sent: dict[str, datetime] = {}
        for item in history:
            text = item.get("text")
            sent_at = item.get("sent_at")
            item_monitor = item.get("monitor")
            if not isinstance(text, str) or not isinstance(sent_at, str):
                continue
            if monitor_key and item_monitor not in (None, monitor_key):
                continue
            try:
                timestamp = datetime.fromisoformat(sent_at)
            except ValueError:
                continue
            last_sent[text] = timestamp
        return last_sent

    def _build_monitors(self) -> list[MonitorRuntime]:
        if not self.config.monitors:
            raise ValueError("monitors must be configured")

        runtimes: list[MonitorRuntime] = []
        monitor_count = len(self.config.monitors)
        for monitor in self.config.monitors:
            key = f"{monitor.window_title_regex}|{monitor.phrase_regex}"
            runtimes.append(
                MonitorRuntime(
                    key=key,
                    config=monitor,
                    detector=WindowTextDetector(
                        monitor.window_title_regex,
                        allow_window_restore=self.config.allow_window_restore,
                        log_throttle_seconds=60,
                    ),
                    sender=build_sender(
                        monitor.email,
                        queue_path=self._queue_path_for_monitor(key, monitor_count),
                        queue_max_items=self.config.email_queue_max_items,
                        queue_max_age_seconds=self.config.email_queue_max_age_seconds,
                        queue_max_attempts=self.config.email_queue_max_attempts,
                        queue_retry_base_seconds=self.config.email_queue_retry_base_seconds,
                    ),
                )
            )
        return runtimes

    def _queue_path_for_monitor(self, monitor_key: str, monitor_count: int) -> Path:
        base = Path(self.config.email_queue_file)
        if monitor_count <= 1:
            return base
        suffix = base.suffix or ".json"
        stem = base.stem
        digest = hashlib.sha256(monitor_key.encode("utf-8")).hexdigest()[:8]
        return base.with_name(f"{stem}-{digest}{suffix}")

    def _send_message(
        self,
        monitor: MonitorRuntime,
        message: str,
        *,
        category: str,
        force_send: bool = False,
    ) -> bool:
        if category not in {"send", "error", "healthcheck"}:
            LOGGER.info(
                "Email notification suppressed for category %s",
                category,
                extra={"category": category},
            )
            return False
        if self.config.log_only_mode and not force_send:
            LOGGER.info(
                "Log-only mode active, skipping send",
                extra={"category": category},
            )
            return False
        sent_any = False

        if monitor.email_disabled:
            now = time.monotonic()
            if now - monitor.last_email_disabled_log_at >= EMAIL_DISABLED_LOG_COOLDOWN_SECONDS:
                monitor.last_email_disabled_log_at = now
                LOGGER.warning(
                    "Email disabled after authentication failure; skipping send",
                    extra={"category": category},
                )
        else:
            sender = self._sender or monitor.sender
            try:
                monitor.last_send_queued = False
                sender.send(message)
                sent_any = True
            except EmailQueued:
                monitor.last_send_queued = True
                LOGGER.info("Message queued for retry", extra={"category": category})
                sent_any = True
            except EmailAuthError as exc:
                monitor.email_disabled = True
                self.status.set_last_error(
                    _safe_status_text(f"erro: falha de autenticação SMTP: {exc}")
                )
                LOGGER.exception(
                    "SMTP authentication failed; disabling email notifications",
                    extra={"category": category},
                )
            except Exception as exc:
                LOGGER.warning(
                    "Failed to send notification: %s",
                    exc,
                    extra={"category": category},
                )

        return sent_any

    def _compute_monitor_backoff_seconds(self, failure_count: int) -> int:
        if failure_count <= 0:
            return 0
        base = max(1, self.config.window_error_backoff_base_seconds)
        maximum = max(base, self.config.window_error_backoff_max_seconds)
        backoff = base * (2 ** (failure_count - 1))
        return min(maximum, backoff)

    def _should_notify_error(self, last_notification_at: float) -> bool:
        cooldown = max(0, self.config.error_notification_cooldown_seconds)
        if cooldown == 0:
            return True
        return (time.monotonic() - last_notification_at) >= cooldown

    def _handle_monitor_error(self, monitor: MonitorRuntime, message: str) -> None:
        monitor.failure_count += 1
        monitor.last_window_error_at = _now_iso()
        self.status.set_last_error(_safe_status_text(message))
        if self._should_notify_error(monitor.last_error_notification_at):
            sent_any = False
            for current in self._monitors:
                if current.key != monitor.key:
                    continue
                if self._send_message(current, message, category="error", force_send=True):
                    sent_any = True
            if sent_any:
                monitor.last_error_notification_at = time.monotonic()
                self.status.set_last_send(_now_iso())

        if monitor.failure_count >= self.config.window_error_circuit_threshold:
            breaker_seconds = max(0, self.config.window_error_circuit_seconds)
            monitor.breaker_until = max(monitor.breaker_until, time.monotonic() + breaker_seconds)
            if LOGGER.isEnabledFor(logging.WARNING):
                LOGGER.warning(
                    "Circuit breaker active for monitor %s (%ss)",
                    _summarize_text(monitor.key),
                    breaker_seconds,
                    extra={"category": "scan"},
                )
            if breaker_seconds > 0:
                critical_message = (
                    f"erro: monitor pausado por {breaker_seconds}s (muitas falhas consecutivas)"
                )
                for current in self._monitors:
                    if current.key != monitor.key:
                        continue
                    self._send_message(
                        current,
                        critical_message,
                        category="error",
                        force_send=True,
                    )
        else:
            backoff_seconds = self._compute_monitor_backoff_seconds(monitor.failure_count)
            if backoff_seconds:
                monitor.breaker_until = max(
                    monitor.breaker_until, time.monotonic() + backoff_seconds
                )
        self.status.set_monitor_state(
            monitor.key,
            failure_count=monitor.failure_count,
            breaker_active=bool(monitor.breaker_until and time.monotonic() < monitor.breaker_until),
        )

    def scan_once(self) -> None:
        """Run a single monitoring scan cycle with a fresh scan context."""
        scan_id = uuid4().hex
        with scan_context(scan_id):
            self._scan_once_impl()

    def _scan_once_impl(self) -> None:  # noqa: C901
        self.status.set_last_scan(_now_iso())
        any_match = False
        self._last_scan_error = False
        self._last_scan_had_match = False
        scan_started = time.perf_counter()
        for index, monitor in enumerate(self._monitors, start=1):
            with log_context(
                monitor_index=index,
                monitor_key=_summarize_text(monitor.key),
            ):
                monitor_started = time.perf_counter()
                monitor_error: str | None = None
                now_mono = time.monotonic()
                if monitor.breaker_until and now_mono < monitor.breaker_until:
                    if index == 1:
                        self.status.set_last_scan_result("PAUSADO (breaker)")
                    LOGGER.info(
                        "Skipping scan; circuit breaker active for monitor",
                        extra={"category": "scan"},
                    )
                    continue
                try:
                    matches = monitor.detector.find_matches(monitor.config.phrase_regex)
                    monitor.failure_count = 0
                    monitor.breaker_until = 0.0
                    monitor.last_window_ok_at = _now_iso()
                    self.status.set_monitor_state(
                        monitor.key,
                        failure_count=0,
                        breaker_active=False,
                    )
                except WindowUnavailableError as exc:
                    message = f"erro: janela indisponível: {exc}"
                    self._handle_monitor_error(monitor, message)
                    self._last_scan_error = True
                    monitor_error = "window_unavailable"
                    if index == 1:
                        self.status.set_last_scan_result("ERRO")
                    continue
                except Exception as exc:
                    message = f"erro: {exc}"
                    self._handle_monitor_error(monitor, message)
                    LOGGER.exception(
                        "Scan error",
                        extra={"category": "error", "event": "scan_error"},
                    )
                    self._last_scan_error = True
                    monitor_error = "exception"
                    if index == 1:
                        self.status.set_last_scan_result("ERRO")
                    continue
                finally:
                    duration_ms = (time.perf_counter() - monitor_started) * 1000
                    if LOGGER.isEnabledFor(logging.INFO):
                        LOGGER.info(
                            "Monitor scan duration %.2fms",
                            duration_ms,
                            extra={
                                "category": "perf",
                                "monitor": _summarize_text(monitor.key),
                                "error": monitor_error or "",
                            },
                        )

            normalized = [_normalize(text) for text in matches if text]
            if index == 1:
                if normalized:
                    self.status.set_last_scan_result(_summarize_text(normalized[0]))
                else:
                    self.status.set_last_scan_result("NENHUM")
            if normalized:
                normalized, removed = dedupe_items(normalized)
                if removed:
                    LOGGER.info(
                        "Deduplicated %s repeated matches in scan",
                        removed,
                        extra={"category": "scan"},
                    )
            now = datetime.now(UTC)
            send_items, skipped = filter_debounce(
                normalized,
                monitor.last_sent,
                self.config.debounce_seconds,
                now,
            )
            if skipped and LOGGER.isEnabledFor(logging.INFO):
                for text, age_seconds in skipped:
                    summary = _summarize_text(text)
                    LOGGER.info(
                        "Debounce active for %s (age %s seconds)",
                        summary,
                        age_seconds,
                        extra={"category": "send"},
                    )

            if send_items and self.config.min_repeat_seconds > 0:
                send_items, skipped = filter_min_repeat(
                    send_items,
                    monitor.last_sent,
                    self.config.min_repeat_seconds,
                    now,
                )
                if skipped and LOGGER.isEnabledFor(logging.INFO):
                    for text, age_seconds in skipped:
                        summary = _summarize_text(text)
                        LOGGER.info(
                            "Min repeat window active for %s (age %s seconds)",
                            summary,
                            age_seconds,
                            extra={"category": "send"},
                        )

            if send_items:
                previous_text = monitor.last_scan_text
                previous_number = monitor.last_scan_number
                filtered_items: list[str] = []
                for text in send_items:
                    if previous_text and text == previous_text:
                        LOGGER.info(
                            "Skipping match identical to previous scan",
                            extra={"category": "send"},
                        )
                        continue
                    current_number = _leading_number(text)
                    if (
                        previous_text
                        and text != previous_text
                        and previous_number is not None
                        and current_number is not None
                        and current_number < previous_number
                    ):
                        LOGGER.info(
                            "Skipping match with lower leading number than previous scan",
                            extra={"category": "send"},
                        )
                        continue
                    filtered_items.append(text)
                send_items = filtered_items

            if normalized:
                any_match = True
                self._last_scan_had_match = True
                self.status.set_last_match(_summarize_text(normalized[0]))
                self.status.set_last_match_at(_now_iso())

            for text in send_items:
                alert_message = _build_alert_message(text, monitor.last_scan_number)
                if self._send_message(monitor, alert_message, category="send", force_send=True):
                    self.status.set_last_send(_now_iso())
                    if monitor.last_send_queued:
                        LOGGER.info("Queued message", extra={"category": "send"})
                    else:
                        LOGGER.info("Sent message", extra={"category": "send"})
                    sent_at = _now_iso()
                    self._history.append({"text": text, "sent_at": sent_at, "monitor": monitor.key})
                    monitor.last_sent[text] = datetime.fromisoformat(sent_at)
            if normalized:
                monitor.last_scan_text = normalized[0]
                monitor.last_scan_number = _leading_number(normalized[0])
            else:
                monitor.last_scan_text = ""
                monitor.last_scan_number = None

        if len(self._history) > self.config.max_history:
            self._history = self._history[-self.config.max_history :]
            for monitor in self._monitors:
                monitor.last_sent = self._build_last_sent_map(self._history, monitor.key)
            self._persist_state()
        elif any_match:
            self._persist_state()

        total_ms = (time.perf_counter() - scan_started) * 1000
        LOGGER.info(
            "Scan loop duration %.2fms",
            total_ms,
            extra={"category": "perf"},
        )

    def _persist_state(self) -> None:
        try:
            _save_state(self._state_path, self._history)
        except Exception:
            self._state_write_errors += 1
            LOGGER.exception(
                "State persistence failed",
                extra={"category": "error"},
            )

    def _handle_error(self, message: str) -> None:
        safe_message = _safe_status_text(message)
        self.status.set_last_error(safe_message)
        try:
            if self.config.log_only_mode:
                LOGGER.info(
                    "Log-only mode active; sending error notification anyway",
                    extra={"category": "error"},
                )
            sent_any = False
            if self._should_notify_error(self._last_error_notification_at):
                for monitor in self._monitors:
                    if self._send_message(
                        monitor,
                        safe_message,
                        category="error",
                        force_send=True,
                    ):
                        sent_any = True
            if sent_any:
                self._last_error_notification_at = time.monotonic()
                self.status.set_last_send(_now_iso())
                LOGGER.info("Sent error notification", extra={"category": "error"})
        except Exception:
            LOGGER.exception(
                "Failed to send error notification",
                extra={"category": "error"},
            )

    def _send_manual_no_match_test(self) -> None:
        now = time.monotonic()
        if now - self._last_no_match_test_at < 30:
            LOGGER.info(
                "Manual no-match test suppressed (cooldown active)",
                extra={"category": "send"},
            )
            return
        self._last_no_match_test_at = now
        message = "verificação: nenhuma correspondência encontrada"
        try:
            sent_any = False
            sent_direct = False
            queued_any = False
            for monitor in self._monitors:
                if self._send_message(monitor, message, category="send", force_send=True):
                    sent_any = True
                    if monitor.last_send_queued:
                        queued_any = True
                    else:
                        sent_direct = True
            if sent_any or self.config.log_only_mode:
                self.status.set_last_send(_now_iso())
                if sent_direct:
                    LOGGER.info("Sent manual no-match test message", extra={"category": "send"})
                elif queued_any:
                    LOGGER.info("Queued manual no-match test message", extra={"category": "send"})
        except Exception as exc:
            error_message = f"erro: falha ao enviar teste de verificação manual: {exc}"
            self._handle_error(error_message)

    def _send_startup_test(self) -> None:
        message = "Z7_SentinelTray iniciado — monitoramento ativo"
        try:
            sent_any = False
            sent_direct = False
            queued_any = False
            for monitor in self._monitors:
                if self._send_message(monitor, message, category="send", force_send=True):
                    sent_any = True
                    if monitor.last_send_queued:
                        queued_any = True
                    else:
                        sent_direct = True
            if sent_any or self.config.log_only_mode:
                self.status.set_last_send(_now_iso())
                if sent_direct:
                    LOGGER.info("Sent startup test message", extra={"category": "send"})
                elif queued_any:
                    LOGGER.info("Queued startup test message", extra={"category": "send"})
        except Exception as exc:
            error_message = f"erro: falha ao enviar teste de inicialização: {exc}"
            self._handle_error(error_message)

    def _send_healthcheck(self) -> None:
        uptime_seconds = int((datetime.now(UTC) - self._started_at).total_seconds())
        self.status.set_uptime_seconds(uptime_seconds)
        snapshot = self.status.snapshot()
        if self.config.healthcheck_send_on_error_only and not snapshot.last_error:
            self.status.set_last_healthcheck(_now_iso())
            return
        try:
            sent_any = False
            sent_direct = False
            queued_any = False
            for monitor in self._monitors:
                status_text = format_status(
                    snapshot,
                    window_title_regex=monitor.config.window_title_regex,
                    phrase_regex=monitor.config.phrase_regex,
                    poll_interval_seconds=self.config.poll_interval_seconds,
                )
                message = f"status: Em execução\n{status_text}"
                safe_message = _safe_status_text(message)
                if self._send_message(monitor, safe_message, category="healthcheck"):
                    sent_any = True
                    if monitor.last_send_queued:
                        queued_any = True
                    else:
                        sent_direct = True
            self.status.set_last_healthcheck(_now_iso())
            if sent_any or self.config.log_only_mode:
                self.status.set_last_send(_now_iso())
                if sent_direct:
                    LOGGER.info("Sent healthcheck message", extra={"category": "send"})
                elif queued_any:
                    LOGGER.info("Queued healthcheck message", extra={"category": "send"})
        except Exception as exc:
            error_message = f"erro: falha ao enviar resumo de saúde: {exc}"
            self._handle_error(error_message)

    def _compute_backoff_seconds(self, error_count: int) -> int:
        if error_count <= 0:
            return 0
        base = max(1, self.config.error_backoff_base_seconds)
        maximum = max(base, self.config.error_backoff_max_seconds)
        backoff = base * (2 ** (error_count - 1))
        return min(maximum, backoff)

    def _update_telemetry(self) -> None:
        snapshot = self.status.snapshot()
        match_age_seconds = 0
        if snapshot.last_match_at:
            try:
                last_match_at = datetime.fromisoformat(snapshot.last_match_at)
                match_age_seconds = int((datetime.now(UTC) - last_match_at).total_seconds())
            except ValueError:
                match_age_seconds = 0
        monitor_payload: list[dict[str, Any]] = []
        for monitor in self._monitors:
            breaker_remaining = max(0.0, monitor.breaker_until - time.monotonic())
            monitor_payload.append(
                {
                    "monitor_key_hash": _hash_value(monitor.key),
                    "window_title_hash": _hash_value(monitor.config.window_title_regex),
                    "phrase_hash": _hash_value(monitor.config.phrase_regex),
                    "failure_count": monitor.failure_count,
                    "breaker_remaining_seconds": int(breaker_remaining),
                    "last_window_ok": _safe_status_text(monitor.last_window_ok_at),
                    "last_window_error": _safe_status_text(monitor.last_window_error_at),
                }
            )
        payload: dict[str, Any] = {
            "updated_at": _now_iso(),
            "app_version": self._app_version,
            "release_date": self._release_date,
            "commit_hash": self._commit_hash,
            "window_title_hash": _hash_value(self._monitors[0].config.window_title_regex),
            "window_title_hashes": [
                _hash_value(monitor.config.window_title_regex) for monitor in self._monitors
            ],
            "monitor_count": len(self._monitors),
            "monitors": monitor_payload,
            "running": snapshot.running,
            "uptime_seconds": snapshot.uptime_seconds,
            "last_scan": _safe_status_text(snapshot.last_scan),
            "last_match": _safe_status_text(snapshot.last_match),
            "last_match_at": _safe_status_text(snapshot.last_match_at),
            "last_match_age_seconds": match_age_seconds,
            "last_send": _safe_status_text(snapshot.last_send),
            "last_error": _safe_status_text(snapshot.last_error),
            "last_healthcheck": _safe_status_text(snapshot.last_healthcheck),
            "error_count": snapshot.error_count,
            "email_queue": self._queue_stats,
            "telemetry_write_errors": self._telemetry_write_errors,
            "state_write_errors": self._state_write_errors,
        }
        try:
            self._telemetry.write(payload)
        except Exception:
            self._telemetry_write_errors += 1
            LOGGER.exception("Telemetry write failed", extra={"category": "error"})

    def _ensure_free_disk(self) -> None:
        try:
            log_dir = Path(self.config.log_file).parent
            usage = shutil.disk_usage(log_dir)
            free_mb = usage.free / (1024 * 1024)
            if free_mb < 50:
                LOGGER.warning(
                    "Low disk space: %.0f MB free in %s",
                    free_mb,
                    log_dir,
                    extra={"category": "error"},
                )
        except Exception as exc:
            LOGGER.warning("Disk check failed: %s", exc, extra={"category": "error"})

    def _drain_queues(self) -> None:
        total = {
            "queued": 0,
            "sent": 0,
            "failed": 0,
            "deferred": 0,
            "oldest_age_seconds": 0,
        }
        for monitor in self._monitors:
            sender = monitor.sender
            if isinstance(sender, QueueingEmailSender):
                try:
                    stats = sender.drain()
                    total["queued"] += stats.queued
                    total["sent"] += stats.sent
                    total["failed"] += stats.failed
                    total["deferred"] += stats.deferred
                    total["oldest_age_seconds"] = max(
                        total["oldest_age_seconds"], stats.oldest_age_seconds
                    )
                except EmailAuthError as exc:
                    monitor.email_disabled = True
                    self.status.set_last_error(
                        _safe_status_text(f"erro: falha de autenticação SMTP: {exc}")
                    )
                except Exception as exc:
                    LOGGER.warning(
                        "Email queue drain failed: %s",
                        exc,
                        extra={"category": "send"},
                    )
        self._queue_stats = total
        self.status.set_email_queue_stats(total)

    def run_loop(  # noqa: C901
        self,
        stop_event: Event,
        manual_scan_event: Event | None = None,
        scan_complete_event: Event | None = None,
        test_message_event: Event | None = None,
        pause_event: Event | None = None,
    ) -> None:
        """Run the main monitoring loop until *stop_event* is set.

        Args:
            stop_event: Setting this event causes the loop to exit cleanly.
            manual_scan_event: Optional event to trigger an immediate scan.
            scan_complete_event: Optional event set after each scan completes.
            test_message_event: Optional event to trigger a test email send.
        """
        self._commit_hash_ready.wait(timeout=2.0)
        setup_logging(
            self.config.log_file,
            log_level=self.config.log_level,
            log_console_level=self.config.log_console_level,
            log_console_enabled=self.config.log_console_enabled,
            log_max_bytes=self.config.log_max_bytes,
            log_backup_count=self.config.log_backup_count,
            log_run_files_keep=self.config.log_run_files_keep,
            app_version=self._app_version,
            release_date=self._release_date,
            commit_hash=self._commit_hash,
        )
        if not _apply_execution_state(True):
            LOGGER.warning(
                "Failed to apply execution state to prevent sleep",
                extra={"category": "startup"},
            )
        try:
            LOGGER.info(
                "Z7_SentinelTray started (beta %s, %s)",
                self._app_version,
                self._release_date,
                extra={"category": "startup"},
            )
            self.status.set_running(True)
            self.status.set_uptime_seconds(0)
            self.status.set_started_at(self._started_at)
            self._update_telemetry()
            error_count = 0

            def _wait_for_next_scan(wait_seconds: int) -> bool:
                if wait_seconds <= 0:
                    return False
                deadline = time.monotonic() + wait_seconds
                while not stop_event.is_set():
                    if manual_scan_event is not None and manual_scan_event.is_set():
                        return True
                    if pause_event is not None and pause_event.is_set():
                        return True
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return False
                    stop_event.wait(min(0.5, remaining))
                return False

            while not stop_event.is_set():
                if pause_event is not None and pause_event.is_set():
                    self.status.set_paused(True)
                    self.status.set_last_scan_result("PAUSADO")
                    self._update_telemetry()
                    while pause_event.is_set() and not stop_event.is_set():
                        stop_event.wait(0.5)
                    self.status.set_paused(False)
                    if stop_event.is_set():
                        break

                loop_started = time.perf_counter()
                try:
                    is_manual = manual_scan_event is not None and manual_scan_event.is_set()
                    if is_manual:
                        manual_scan_event.clear()
                        LOGGER.info("Manual scan requested", extra={"category": "control"})
                    if test_message_event is not None and test_message_event.is_set():
                        test_message_event.clear()
                        LOGGER.info("Test message requested", extra={"category": "control"})
                        self._send_startup_test()
                    disk_started = time.perf_counter()
                    self._ensure_free_disk()
                    LOGGER.debug(
                        "Disk check duration %.2fms",
                        (time.perf_counter() - disk_started) * 1000,
                        extra={"category": "perf"},
                    )
                    now = time.monotonic()
                    if now >= self._next_queue_drain:
                        queue_started = time.perf_counter()
                        self._drain_queues()
                        LOGGER.info(
                            "Queue drain duration %.2fms",
                            (time.perf_counter() - queue_started) * 1000,
                            extra={"category": "perf"},
                        )
                        self._next_queue_drain = now + 30
                    if (
                        not is_manual
                        and self.config.pause_on_user_active
                        and get_idle_seconds() < self.config.pause_idle_threshold_seconds
                    ):
                        self.status.set_last_scan_result("PAUSADO (usuário ativo)")
                        LOGGER.debug(
                            "Scan skipped: user is active (idle < %ss)",
                            self.config.pause_idle_threshold_seconds,
                            extra={"category": "scan"},
                        )
                    else:
                        self.scan_once()
                        if self._last_scan_error:
                            error_count += 1
                            self.status.increment_error_count()
                        else:
                            self.status.set_last_error("")
                            error_count = 0
                            if is_manual and not self._last_scan_had_match:
                                self._send_manual_no_match_test()
                except WindowUnavailableError as exc:
                    self._handle_error(f"erro: janela indisponível: {exc}")
                    LOGGER.info(
                        "Skipping scan; %s",
                        exc,
                        extra={"category": "scan"},
                    )
                except Exception as exc:
                    message = f"erro: {exc}"
                    self._handle_error(message)
                    LOGGER.exception("Loop error", extra={"category": "error"})
                    error_count += 1
                    self.status.increment_error_count()
                finally:
                    LOGGER.info(
                        "Loop iteration duration %.2fms",
                        (time.perf_counter() - loop_started) * 1000,
                        extra={"category": "perf"},
                    )

                self.status.set_uptime_seconds(
                    int((datetime.now(UTC) - self._started_at).total_seconds())
                )
                now = time.monotonic()
                if now >= self._next_healthcheck:
                    self._send_healthcheck()
                    self._next_healthcheck = now + self.config.healthcheck_interval_seconds

                self._update_telemetry()

                if scan_complete_event is not None:
                    scan_complete_event.set()

                backoff_seconds = self._compute_backoff_seconds(error_count)
                wait_seconds = max(self.config.poll_interval_seconds, backoff_seconds)
                if backoff_seconds:
                    LOGGER.info(
                        "Backoff enabled: %s seconds",
                        backoff_seconds,
                        extra={"category": "control"},
                    )
                if _wait_for_next_scan(wait_seconds):
                    continue

            self.status.set_running(False)
        finally:
            _apply_execution_state(False)


def run(config: AppConfig) -> None:
    """Create a ``Notifier`` from *config* and start the blocking run loop.

    Args:
        config: Fully validated application configuration.
    """
    status = StatusStore()
    notifier = Notifier(config=config, status=status)
    stop_event = Event()
    notifier.run_loop(stop_event)
