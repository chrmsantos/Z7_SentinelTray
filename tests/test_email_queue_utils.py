from __future__ import annotations

from datetime import UTC, datetime, timedelta

from z7_sentineltray.email_queue_utils import (
    build_new_item,
    compute_next_attempt,
    compute_oldest_age_seconds,
    normalize_item,
    prune_items,
)


def test_normalize_item_rejects_empty_message() -> None:
    now = datetime.now(UTC)
    assert normalize_item({"message": " "}, now) is None


def test_build_new_item_sets_fields() -> None:
    now = datetime.now(UTC)
    item = build_new_item("hello", now)
    assert item["message"] == "hello"
    assert item["attempts"] == 0


def test_prune_items_respects_limits() -> None:
    now = datetime.now(UTC)
    old = now - timedelta(seconds=100)
    items = [
        {
            "message": "a",
            "created_at": old.isoformat(),
            "attempts": 0,
            "next_attempt_at": now.isoformat(),
        },
        {
            "message": "b",
            "created_at": now.isoformat(),
            "attempts": 2,
            "next_attempt_at": now.isoformat(),
        },
    ]
    pruned = prune_items(items, now=now, max_items=1, max_age_seconds=50, max_attempts=2)
    assert len(pruned) == 1
    assert pruned[0]["message"] == "b"


def test_compute_next_attempt_backoff() -> None:
    now = datetime.now(UTC)
    next_at = compute_next_attempt(now, attempts=3, retry_base_seconds=10)
    assert next_at > now


def test_compute_oldest_age_seconds() -> None:
    now = datetime.now(UTC)
    items = [
        {"message": "a", "created_at": (now - timedelta(seconds=30)).isoformat()},
        {"message": "b", "created_at": (now - timedelta(seconds=10)).isoformat()},
    ]
    assert compute_oldest_age_seconds(items, now) >= 30
