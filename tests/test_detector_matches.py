from __future__ import annotations

import pytest

from z7_sentineltray.detector import WindowTextDetector


def test_find_matches_accepts_whitespace_phrase(monkeypatch: pytest.MonkeyPatch) -> None:
    detector = WindowTextDetector("APP", allow_window_restore=True)
    monkeypatch.setattr(detector, "_iter_texts", lambda: ["one", "two"])

    assert detector.find_matches("   ") == ["one", "two"]


def test_find_matches_invalid_regex(monkeypatch: pytest.MonkeyPatch) -> None:
    detector = WindowTextDetector("APP", allow_window_restore=True)
    monkeypatch.setattr(detector, "_iter_texts", lambda: ["one"])

    with pytest.raises(ValueError, match="Invalid phrase regex"):
        detector.find_matches("(")


def test_find_matches_includes_window_title(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeWindow:
        def window_text(self) -> str:
            return "Title"

        def descendants(self):
            return []

        def is_enabled(self) -> bool:
            return True

    detector = WindowTextDetector("APP", allow_window_restore=False)
    monkeypatch.setattr(detector, "_get_window", lambda: FakeWindow())
    monkeypatch.setattr(detector, "_window_exists", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        detector, "_ensure_foreground_and_maximized", lambda *_args, **_kwargs: None
    )

    assert detector.find_matches("Title") == ["Title"]
