"""Utilities for deduplication and debounce filtering of scan results."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime


def dedupe_items(items: Iterable[str]) -> tuple[list[str], int]:
    """Remove duplicate strings while preserving first-occurrence order.

    Args:
        items: Sequence of strings to deduplicate.

    Returns:
        A tuple of ``(deduped_list, removed_count)``.
    """
    deduped: list[str] = []
    seen: set[str] = set()
    removed = 0
    for item in items:
        if item in seen:
            removed += 1
            continue
        seen.add(item)
        deduped.append(item)
    return deduped, removed


def filter_debounce(
    items: Iterable[str],
    last_sent: dict[str, datetime],
    debounce_seconds: int,
    now: datetime,
) -> tuple[list[str], list[tuple[str, int]]]:
    """Filter *items* by debounce window, suppressing recently sent items.

    Args:
        items: Candidate strings from the current scan.
        last_sent: Mapping of text → last-sent timestamp.
        debounce_seconds: Minimum seconds that must pass before resending.
        now: Current timestamp used for age comparison.

    Returns:
        A tuple of ``(selected, skipped)`` where *skipped* contains
        ``(text, age_seconds)`` pairs for suppressed items.
    """
    if debounce_seconds <= 0:
        return list(items), []

    selected: list[str] = []
    skipped: list[tuple[str, int]] = []
    for text in items:
        sent_at = last_sent.get(text)
        if sent_at is None:
            selected.append(text)
            continue
        age_seconds = int((now - sent_at).total_seconds())
        if age_seconds >= debounce_seconds:
            selected.append(text)
        else:
            skipped.append((text, age_seconds))
    return selected, skipped


def filter_min_repeat(
    items: Iterable[str],
    last_sent: dict[str, datetime],
    min_repeat_seconds: int,
    now: datetime,
) -> tuple[list[str], list[tuple[str, int]]]:
    """Filter *items* by minimum repeat interval, skipping items sent too recently.

    Behaves like :func:`filter_debounce` but uses a separate configured
    threshold (``min_repeat_seconds``) that controls how soon the *same*
    text can be resent after a successful send.

    Args:
        items: Candidate strings from the current scan.
        last_sent: Mapping of text → last-sent timestamp.
        min_repeat_seconds: Minimum seconds between repeated sends.
        now: Current timestamp used for age comparison.

    Returns:
        A tuple of ``(selected, skipped)`` where *skipped* contains
        ``(text, age_seconds)`` pairs for suppressed items.
    """
    if min_repeat_seconds <= 0:
        return list(items), []

    selected: list[str] = []
    skipped: list[tuple[str, int]] = []
    for text in items:
        sent_at = last_sent.get(text)
        if sent_at is None:
            selected.append(text)
            continue
        age_seconds = int((now - sent_at).total_seconds())
        if age_seconds >= min_repeat_seconds:
            selected.append(text)
        else:
            skipped.append((text, age_seconds))
    return selected, skipped
