"""Utilities for managing the persistent e-mail retry queue."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any


def parse_timestamp(value: str) -> datetime | None:
    """Parse an ISO 8601 timestamp string.

    Args:
        value: ISO 8601 string (e.g. ``"2026-04-29T12:00:00+00:00"``).

    Returns:
        Parsed :class:`~datetime.datetime` or ``None`` if parsing fails.
    """
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def normalize_item(raw: dict[str, Any], now: datetime) -> dict[str, object] | None:
    """Validate and normalise a raw queue item dict loaded from disk.

    Args:
        raw: Mapping read from the JSON queue file.
        now: Current timestamp used to fill in missing ``next_attempt_at``.

    Returns:
        Normalised item dict, or ``None`` if *raw* is invalid.
    """
    message = raw.get("message")
    if not isinstance(message, str) or not message.strip():
        return None
    created_at = raw.get("created_at")
    if not isinstance(created_at, str):
        created_at = now.isoformat()
    attempts = int(raw.get("attempts", 0))
    next_attempt_at = raw.get("next_attempt_at")
    if not isinstance(next_attempt_at, str):
        next_attempt_at = now.isoformat()
    return {
        "message": message,
        "created_at": created_at,
        "attempts": attempts,
        "next_attempt_at": next_attempt_at,
    }


def build_new_item(message: str, now: datetime) -> dict[str, object]:
    """Build a fresh queue item dict for an unsent message.

    Args:
        message: The e-mail body text to queue.
        now: Timestamp to record as ``created_at`` and ``next_attempt_at``.

    Returns:
        Queue item dict ready to be appended to the queue.
    """
    return {
        "message": message,
        "created_at": now.isoformat(),
        "attempts": 0,
        "next_attempt_at": now.isoformat(),
    }


def prune_items(
    items: list[dict[str, object]],
    *,
    now: datetime,
    max_items: int,
    max_age_seconds: int,
    max_attempts: int,
) -> list[dict[str, object]]:
    """Remove stale, over-attempted, or excess items from the queue.

    Args:
        items: Current queue contents.
        now: Current timestamp for age computation.
        max_items: Maximum number of items to retain (0 = unlimited).
        max_age_seconds: Drop items older than this (0 = unlimited).
        max_attempts: Drop items that have been attempted more times (0 = unlimited).

    Returns:
        Pruned list of queue items.
    """
    pruned: list[dict[str, object]] = []
    for item in items:
        created_raw = item.get("created_at")
        created_at = parse_timestamp(created_raw) if isinstance(created_raw, str) else None
        attempts = int(item.get("attempts", 0))
        if max_attempts and attempts > max_attempts:
            continue
        if max_age_seconds and created_at and (now - created_at).total_seconds() > max_age_seconds:
            continue
        pruned.append(item)

    if max_items and len(pruned) > max_items:
        pruned = pruned[-max_items:]
    return pruned


def compute_next_attempt(now: datetime, *, attempts: int, retry_base_seconds: int) -> datetime:
    """Compute the next retry timestamp using exponential back-off.

    Args:
        now: Current timestamp.
        attempts: Number of delivery attempts already made.
        retry_base_seconds: Base delay in seconds (doubling with each retry).

    Returns:
        Timestamp after which the next attempt should be made.
    """
    if not attempts:
        return now
    delay = retry_base_seconds * (2 ** max(0, attempts - 1))
    return now + timedelta(seconds=delay)


def compute_oldest_age_seconds(items: list[dict[str, object]], now: datetime) -> int:
    """Return the age in seconds of the oldest item in *items*.

    Args:
        items: Queue items, each with an optional ``created_at`` ISO string.
        now: Current timestamp for age calculation.

    Returns:
        Age in whole seconds of the oldest item, or ``0`` if *items* is empty.
    """
    created_times = [
        parse_timestamp(item.get("created_at"))
        for item in items
        if isinstance(item.get("created_at"), str)
    ]
    created_times = [value for value in created_times if value]
    if not created_times:
        return 0
    oldest = min(created_times)
    return int((now - oldest).total_seconds())
