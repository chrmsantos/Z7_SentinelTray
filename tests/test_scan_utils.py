from __future__ import annotations

from datetime import UTC, datetime, timedelta

from z7_sentineltray.scan_utils import dedupe_items, filter_debounce, filter_min_repeat


def test_dedupe_items_preserves_order() -> None:
    items = ["a", "b", "a", "c", "b"]
    deduped, removed = dedupe_items(items)
    assert deduped == ["a", "b", "c"]
    assert removed == 2


def test_filter_debounce_respects_threshold() -> None:
    now = datetime.now(UTC)
    last_sent = {
        "old": now - timedelta(seconds=120),
        "new": now - timedelta(seconds=5),
    }

    selected, skipped = filter_debounce(
        ["old", "new", "fresh"],
        last_sent,
        debounce_seconds=30,
        now=now,
    )

    assert "old" in selected
    assert "fresh" in selected
    assert ("new", 5) in skipped


def test_filter_min_repeat_respects_threshold() -> None:
    now = datetime.now(UTC)
    last_sent = {
        "old": now - timedelta(seconds=120),
        "new": now - timedelta(seconds=5),
    }

    selected, skipped = filter_min_repeat(
        ["old", "new", "fresh"],
        last_sent,
        min_repeat_seconds=60,
        now=now,
    )

    assert "old" in selected
    assert "fresh" in selected
    assert ("new", 5) in skipped
