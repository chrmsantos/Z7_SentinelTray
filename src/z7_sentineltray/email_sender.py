"""SMTP email delivery with retry, disk-based queuing, and auth-error handling."""

from __future__ import annotations

import json
import logging
import smtplib
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.message import EmailMessage
from pathlib import Path

from .config import EmailConfig
from .email_queue_utils import (
    build_new_item,
    compute_next_attempt,
    compute_oldest_age_seconds,
    normalize_item,
    parse_timestamp,
    prune_items,
)
from .io_utils import read_json_safe
from .telemetry import atomic_write_text

LOGGER = logging.getLogger(__name__)


class EmailAuthError(RuntimeError):
    """Raised when SMTP authentication fails and sending should be disabled."""


class EmailQueued(RuntimeError):  # noqa: N818
    """Raised when a message is queued after a transient failure."""


_CATEGORY_LABEL: dict[str, str] = {
    "Alert": "Alerta",
    "Error": "Erro",
    "Status": "Status",
    "Verificação": "Verificação",
}


def _build_subject(subject: str, category: str) -> str:
    if category == "Alert":
        return "Z7_SentinelTray — Correspondência Detectada"
    if category == "Error":
        return "Z7_SentinelTray — Erro Detectado"
    if category == "Status":
        return "Z7_SentinelTray — Status do sistema"
    if category == "Verificação":
        return "Z7_SentinelTray — Verificação Manual"
    base = (subject or "").strip()
    if base:
        cleaned = base
        for _prefix in ("zwave z7_sentineltray", "z7_sentineltray"):
            while cleaned.lower().startswith(_prefix):
                cleaned = cleaned[len(_prefix) :].strip()
                cleaned = cleaned.lstrip("-\u2013\u2014:|/").strip()
                if not cleaned:
                    break
        base = cleaned
    if base:
        return f"Z7_SentinelTray {base} - {category}"
    return f"Z7_SentinelTray {category}"


def _build_body(message: str) -> tuple[str, str]:
    text = (message or "").strip()
    category = "Alert"
    details = text
    if text.lower().startswith("error:") or text.lower().startswith("erro:"):
        category = "Error"
        details = text.split(":", 1)[1].strip() or "Ocorreu um erro."
    elif text.lower().startswith("info:"):
        category = "Info"
        details = text.split(":", 1)[1].strip() or "Atualização do sistema."
    elif text.lower().startswith("status:"):
        category = "Status"
        details = text.split(":", 1)[1].strip() or "Sistema em execução."
    elif text.lower().startswith("verificação:") or text.lower().startswith("verificacao:"):
        category = "Verificação"
        details = text.split(":", 1)[1].strip() or "Verificação realizada."

    if not details:
        details = "Sem detalhes adicionais."

    if category == "Alert" and details == text:
        details = "O seguinte texto foi encontrado na tela:\n" + details

    label = _CATEGORY_LABEL.get(category, category)
    body = (
        "Z7_SentinelTray\n\n"
        f"{label}:\n"
        f"{details}\n\n"
        "Esta é uma mensagem automática do Z7_SentinelTray."
    )
    return category, body


class EmailSender:
    """Abstract base class for email delivery backends."""

    def send(self, message: str) -> None:
        """Send *message*; raise on unrecoverable failure."""
        raise NotImplementedError()


@dataclass
class SmtpEmailSender(EmailSender):
    """Synchronous SMTP sender with configurable TLS and retry."""

    config: EmailConfig

    @staticmethod
    def _is_auth_error(exc: smtplib.SMTPException) -> bool:
        if isinstance(exc, smtplib.SMTPAuthenticationError):
            return True
        if isinstance(exc, smtplib.SMTPResponseException):
            return exc.smtp_code in {534, 535}
        return False

    def send(self, message: str) -> None:  # noqa: C901
        """Send *message* via SMTP; raise ``EmailAuthError`` on authentication failure."""
        if not self.config.smtp_host:
            raise ValueError("smtp_host is required")
        if not self.config.from_address:
            raise ValueError("from_address is required")
        if not self.config.to_addresses:
            raise ValueError("to_addresses is required")

        category, body = _build_body(message)
        if category == "Info":
            LOGGER.info(
                "Info notification suppressed",
                extra={"category": "send"},
            )
            return

        email = EmailMessage()
        email["From"] = self.config.from_address
        email["To"] = ", ".join(self.config.to_addresses)
        email["Subject"] = _build_subject(self.config.subject, category)
        email.set_content(body, charset="utf-8")

        attempts = max(0, self.config.retry_attempts)
        backoff = max(0, self.config.retry_backoff_seconds)

        for attempt in range(attempts + 1):
            try:
                with smtplib.SMTP(
                    self.config.smtp_host,
                    self.config.smtp_port,
                    timeout=self.config.timeout_seconds,
                ) as client:
                    if self.config.use_tls:
                        client.starttls()
                    if self.config.smtp_username or self.config.smtp_password:
                        client.login(self.config.smtp_username, self.config.smtp_password)
                    client.send_message(email)
            except smtplib.SMTPException as exc:
                if SmtpEmailSender._is_auth_error(exc):
                    LOGGER.exception(
                        "SMTP authentication failed (check app password)",
                        extra={"category": "send"},
                    )
                    raise EmailAuthError("SMTP authentication failed") from exc
                if attempt >= attempts:
                    LOGGER.exception(
                        "SMTP failure after %s attempts",
                        attempts + 1,
                        extra={"category": "send"},
                    )
                    raise
                LOGGER.warning(
                    "SMTP failure, retrying: %s",
                    exc,
                    extra={"category": "send"},
                )
                if backoff:
                    time.sleep(backoff * (2**attempt))
            else:
                return


def validate_smtp_credentials(config: EmailConfig) -> None:
    """Validate SMTP credentials by performing a live connection and login."""
    if not config.smtp_host:
        raise ValueError("smtp_host is required")
    if not config.smtp_username and not config.smtp_password:
        raise ValueError("smtp_username or smtp_password is required")

    try:
        with smtplib.SMTP(
            config.smtp_host,
            config.smtp_port,
            timeout=config.timeout_seconds,
        ) as client:
            if config.use_tls:
                client.starttls()
            client.login(config.smtp_username, config.smtp_password)
    except smtplib.SMTPException as exc:
        if SmtpEmailSender._is_auth_error(exc):
            LOGGER.exception(
                "SMTP authentication failed during startup validation",
                extra={"category": "startup"},
            )
            raise EmailAuthError("SMTP authentication failed") from exc
        raise RuntimeError(f"SMTP validation failed: {exc}") from exc


@dataclass
class QueueStats:
    """Email queue statistics snapshot."""

    queued: int
    sent: int
    failed: int
    deferred: int
    oldest_age_seconds: int


class DiskEmailQueue:
    """Persistent on-disk email queue with retry scheduling."""

    def __init__(
        self,
        path: Path,
        *,
        max_items: int,
        max_age_seconds: int,
        max_attempts: int,
        retry_base_seconds: int,
    ) -> None:
        self._path = path
        self._max_items = max_items
        self._max_age_seconds = max_age_seconds
        self._max_attempts = max_attempts
        self._retry_base_seconds = retry_base_seconds

    def _now(self) -> datetime:
        return datetime.now(UTC)

    def _load_items(self) -> list[dict[str, object]]:
        if not self._path.exists():
            return []
        data = read_json_safe(self._path, default=[], context="email queue")
        if not isinstance(data, list):
            return []
        items: list[dict[str, object]] = []
        now = self._now()
        for raw in data:
            if not isinstance(raw, dict):
                continue
            normalized = normalize_item(raw, now)
            if normalized:
                items.append(normalized)
        return items

    def _save_items(self, items: list[dict[str, object]]) -> None:
        payload = json.dumps(items, ensure_ascii=False, indent=2)
        try:
            atomic_write_text(self._path, payload, encoding="utf-8")
        except Exception:
            LOGGER.exception(
                "Failed to persist email queue",
                extra={"category": "send"},
            )
            raise

    def enqueue(self, message: str) -> None:
        """Append *message* to the queue and prune stale items."""
        items = self._load_items()
        items.append(build_new_item(message, self._now()))
        items = prune_items(
            items,
            now=self._now(),
            max_items=self._max_items,
            max_age_seconds=self._max_age_seconds,
            max_attempts=self._max_attempts,
        )
        self._save_items(items)

    def drain(self, send_func: Callable[[str], None]) -> QueueStats:
        """Attempt to send all queued messages using *send_func*; return stats."""
        items = self._load_items()
        if not items:
            return QueueStats(queued=0, sent=0, failed=0, deferred=0, oldest_age_seconds=0)

        now = self._now()
        remaining: list[dict[str, object]] = []
        sent = 0
        failed = 0
        deferred = 0

        for item in items:
            message = str(item.get("message", ""))
            next_attempt_raw = item.get("next_attempt_at")
            next_attempt_at = (
                parse_timestamp(next_attempt_raw) if isinstance(next_attempt_raw, str) else None
            )
            if next_attempt_at and next_attempt_at > now:
                deferred += 1
                remaining.append(item)
                continue
            try:
                send_func(message)
                sent += 1
                continue
            except EmailAuthError:
                raise
            except Exception:
                failed += 1
                attempts = int(item.get("attempts", 0)) + 1
                next_attempt_at = compute_next_attempt(
                    now,
                    attempts=attempts,
                    retry_base_seconds=self._retry_base_seconds,
                )
                item["attempts"] = attempts
                item["next_attempt_at"] = next_attempt_at.isoformat()
                remaining.append(item)

        remaining = prune_items(
            remaining,
            now=now,
            max_items=self._max_items,
            max_age_seconds=self._max_age_seconds,
            max_attempts=self._max_attempts,
        )
        self._save_items(remaining)
        oldest_age_seconds = compute_oldest_age_seconds(remaining, now)

        return QueueStats(
            queued=len(remaining),
            sent=sent,
            failed=failed,
            deferred=deferred,
            oldest_age_seconds=oldest_age_seconds,
        )

    def get_stats(self) -> QueueStats:
        """Return queue statistics without attempting any sends."""
        items = self._load_items()
        if not items:
            return QueueStats(queued=0, sent=0, failed=0, deferred=0, oldest_age_seconds=0)
        now = self._now()
        oldest_age_seconds = compute_oldest_age_seconds(items, now)
        return QueueStats(
            queued=len(items),
            sent=0,
            failed=0,
            deferred=0,
            oldest_age_seconds=oldest_age_seconds,
        )


@dataclass
class QueueingEmailSender(EmailSender):
    """Email sender that drains a ``DiskEmailQueue`` before attempting live sends."""

    sender: SmtpEmailSender
    queue: DiskEmailQueue
    cumulative_sent: int = field(default=0, init=False)
    cumulative_failed: int = field(default=0, init=False)

    def send(self, message: str) -> None:
        """Drain the queue, then send *message*; queue on transient failure."""
        try:
            self.drain()
        except EmailAuthError:
            raise
        except Exception as exc:
            LOGGER.warning("Failed to drain email queue: %s", exc, extra={"category": "send"})

        try:
            self.sender.send(message)
            self.cumulative_sent += 1
        except EmailAuthError:
            raise
        except Exception as exc:
            LOGGER.warning(
                "Transient send failure; queued for retry: %s",
                exc,
                extra={"category": "send"},
            )
            try:
                self.queue.enqueue(message)
                self.cumulative_failed += 1
            except Exception:
                LOGGER.exception(
                    "Failed to enqueue message after send failure",
                    extra={"category": "send"},
                )
                raise
            raise EmailQueued("Message queued for retry") from exc

    def drain(self) -> QueueStats:
        """Drain the underlying queue and return stats."""
        stats = self.queue.drain(self.sender.send)
        self.cumulative_sent += stats.sent
        self.cumulative_failed += stats.failed
        return stats

    def get_queue_stats(self) -> QueueStats:
        """Return queue stats without sending."""
        stats = self.queue.get_stats()
        return QueueStats(
            queued=stats.queued,
            sent=self.cumulative_sent,
            failed=self.cumulative_failed,
            deferred=stats.deferred,
            oldest_age_seconds=stats.oldest_age_seconds,
        )


def build_sender(
    config: EmailConfig,
    *,
    queue_path: Path,
    queue_max_items: int = 500,
    queue_max_age_seconds: int = 86400,
    queue_max_attempts: int = 10,
    queue_retry_base_seconds: int = 30,
) -> EmailSender:
    """Build a ``QueueingEmailSender`` wrapping a ``SmtpEmailSender`` and ``DiskEmailQueue``."""
    base_sender = SmtpEmailSender(config=config)
    queue = DiskEmailQueue(
        queue_path,
        max_items=max(1, queue_max_items),
        max_age_seconds=max(0, queue_max_age_seconds),
        max_attempts=max(0, queue_max_attempts),
        retry_base_seconds=max(0, queue_retry_base_seconds),
    )
    return QueueingEmailSender(sender=base_sender, queue=queue)
