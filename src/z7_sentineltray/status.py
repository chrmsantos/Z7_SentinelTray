"""Thread-safe status store and snapshot model for the running application."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from threading import Lock


@dataclass(frozen=True)
class StatusSnapshot:
    """Immutable point-in-time snapshot of application status.

    All fields are read-only; a new snapshot is created for each read.
    """

    running: bool
    paused: bool
    last_scan: str
    last_scan_result: str
    last_match: str
    last_match_at: str
    last_send: str
    last_error: str
    last_healthcheck: str
    uptime_seconds: int
    started_at: datetime | None
    error_count: int
    email_queue: dict[str, int]
    monitor_failures: dict[str, int]
    monitor_breakers_active: dict[str, bool]
    breaker_active_count: int
    active_windows: list[str]
    update_status: str


class StatusStore:
    """Thread-safe container for live application state.

    All setter methods acquire an internal :class:`~threading.Lock` so
    they are safe to call from any thread.  Call :meth:`snapshot` to
    obtain an immutable :class:`StatusSnapshot` copy.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._running = False
        self._paused = False
        self._last_scan = ""
        self._last_scan_result = ""
        self._last_match = ""
        self._last_match_at = ""
        self._last_send = ""
        self._last_error = ""
        self._last_healthcheck = ""
        self._uptime_seconds = 0
        self._started_at: datetime | None = None
        self._error_count = 0
        self._email_queue = {
            "queued": 0,
            "sent": 0,
            "failed": 0,
            "deferred": 0,
            "oldest_age_seconds": 0,
        }
        self._monitor_failures: dict[str, int] = {}
        self._monitor_breakers_active: dict[str, bool] = {}
        self._active_windows: list[str] = []
        self._update_status = "Não verificado"

    def set_running(self, value: bool) -> None:
        """Set the *running* flag."""
        with self._lock:
            self._running = value

    def set_paused(self, value: bool) -> None:
        """Set the *paused* flag."""
        with self._lock:
            self._paused = value

    def set_last_scan(self, value: str) -> None:
        """Record the ISO timestamp of the most recent scan."""
        with self._lock:
            self._last_scan = value

    def set_last_scan_result(self, value: str) -> None:
        """Record a brief description of the last scan outcome."""
        with self._lock:
            self._last_scan_result = value

    def set_last_match(self, value: str) -> None:
        """Record the most recently detected match text (sanitised)."""
        with self._lock:
            self._last_match = value

    def set_last_match_at(self, value: str) -> None:
        """Record the ISO timestamp of the last match."""
        with self._lock:
            self._last_match_at = value

    def set_last_send(self, value: str) -> None:
        """Record the ISO timestamp of the last successful e-mail send."""
        with self._lock:
            self._last_send = value

    def set_last_error(self, value: str) -> None:
        """Record the most recent error message (sanitised)."""
        with self._lock:
            self._last_error = value

    def set_last_healthcheck(self, value: str) -> None:
        """Record the ISO timestamp of the last health-check message."""
        with self._lock:
            self._last_healthcheck = value

    def set_uptime_seconds(self, value: int) -> None:
        """Update the cumulative uptime counter in seconds."""
        with self._lock:
            self._uptime_seconds = value

    def set_started_at(self, value: datetime | None) -> None:
        """Record the process start timestamp."""
        with self._lock:
            self._started_at = value

    def increment_error_count(self) -> None:
        """Atomically increment the total error counter by one."""
        with self._lock:
            self._error_count += 1

    def set_email_queue_stats(self, value: dict[str, int]) -> None:
        """Update the e-mail queue statistics dict."""
        with self._lock:
            self._email_queue = dict(value)

    def set_monitor_state(self, key: str, *, failure_count: int, breaker_active: bool) -> None:
        """Update failure count and circuit-breaker state for a named monitor."""
        with self._lock:
            self._monitor_failures[key] = max(0, int(failure_count))
            self._monitor_breakers_active[key] = bool(breaker_active)

    def set_active_windows(self, value: list[str]) -> None:
        """Record the list of currently active window titles."""
        with self._lock:
            self._active_windows = list(value)

    def set_update_status(self, value: str) -> None:
        """Record the current update check status."""
        with self._lock:
            self._update_status = value

    def snapshot(self) -> StatusSnapshot:
        """Return an immutable copy of the current application status."""
        with self._lock:
            breaker_active_count = sum(
                1 for active in self._monitor_breakers_active.values() if active
            )
            return StatusSnapshot(
                running=self._running,
                paused=self._paused,
                last_scan=self._last_scan,
                last_scan_result=self._last_scan_result,
                last_match=self._last_match,
                last_match_at=self._last_match_at,
                last_send=self._last_send,
                last_error=self._last_error,
                last_healthcheck=self._last_healthcheck,
                uptime_seconds=self._uptime_seconds,
                started_at=self._started_at,
                error_count=self._error_count,
                email_queue=dict(self._email_queue),
                monitor_failures=dict(self._monitor_failures),
                monitor_breakers_active=dict(self._monitor_breakers_active),
                breaker_active_count=breaker_active_count,
                active_windows=list(self._active_windows),
                update_status=self._update_status,
            )


def _format_timestamp(value: str) -> str:
    if not value:
        return ""
    try:
        timestamp = datetime.fromisoformat(value)
        return timestamp.strftime("%d-%m-%Y - %H:%M")
    except ValueError:
        return value


def format_timestamp(value: str) -> str:
    """Re-export of the internal timestamp formatter for external callers."""
    return _format_timestamp(value)


def _format_next_check(last_scan: str, poll_interval_seconds: int | None) -> str:
    if not last_scan or not poll_interval_seconds:
        return ""
    try:
        timestamp = datetime.fromisoformat(last_scan)
        next_timestamp = timestamp + timedelta(seconds=int(poll_interval_seconds))
        return next_timestamp.strftime("%d-%m-%Y - %H:%M")
    except ValueError:
        return ""


def _format_failure_summary(failures: dict[str, int]) -> str:
    if not failures:
        return ""
    items = [(key, count) for key, count in failures.items() if count > 0]
    if not items:
        return ""
    items.sort(key=lambda item: item[1], reverse=True)
    summary_parts = []
    for key, count in items[:3]:
        label = key if len(key) <= 32 else f"{key[:29]}..."
        summary_parts.append(f"{label}={count}")
    return ", ".join(summary_parts)


def format_status(
    snapshot: StatusSnapshot,
    *,
    window_title_regex: str = "",
    phrase_regex: str = "",
    poll_interval_seconds: int | None = None,
) -> str:
    """Format a human-readable status summary from *snapshot*.

    Args:
        snapshot: Current application status snapshot.
        window_title_regex: The configured window-title regex (for display).
        phrase_regex: The configured phrase regex (for display).
        poll_interval_seconds: Poll interval used to compute the next check time.

    Returns:
        Multi-line Portuguese status string suitable for the console/GUI display.
    """
    running = "sim" if snapshot.running else "não"
    phrase_label = phrase_regex or "<qualquer texto>"
    window_label = window_title_regex or "<janela configurada>"
    last_scan = _format_timestamp(snapshot.last_scan)
    next_check = _format_next_check(snapshot.last_scan, poll_interval_seconds)
    last_identification = _format_timestamp(snapshot.last_match) or snapshot.last_match
    last_match_at = _format_timestamp(snapshot.last_match_at)
    failure_summary = _format_failure_summary(snapshot.monitor_failures) or "nenhuma"
    lines = [
        f"Em execução: {running}",
        f"Janela monitorada: {window_label}",
        f"Texto monitorado: {phrase_label}",
        f"Última verificação: {last_scan}",
        f"Próxima verificação: {next_check}",
        f"Última detecção: {last_identification}",
        f"Horário da última correspondência: {last_match_at}",
        f"Último alerta enviado: {_format_timestamp(snapshot.last_send)}",
        f"Último erro registrado: {_format_timestamp(snapshot.last_error)}",
        f"Último resumo de saúde: {_format_timestamp(snapshot.last_healthcheck)}",
        f"E-mails pendentes na fila: {snapshot.email_queue.get('queued', 0)}",
        f"Disjuntores ativos: {snapshot.breaker_active_count}",
        f"Falhas nos monitores: {failure_summary}",
        f"Tempo ativo (segundos): {snapshot.uptime_seconds}",
        f"Total de erros: {snapshot.error_count}",
    ]
    return "\n".join(lines)
