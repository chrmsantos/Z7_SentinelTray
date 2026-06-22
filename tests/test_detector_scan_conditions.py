from __future__ import annotations

import pytest

from z7_sentineltray.detector import WindowTextDetector, WindowUnavailableError


class FakeElement:
    def __init__(self, text: str) -> None:
        self._text = text

    def window_text(self) -> str:
        return self._text


class FakeWindow:
    def __init__(
        self,
        *,
        exists: bool = True,
        foreground: bool = True,
        maximized: bool = True,
        minimized: bool = False,
    ) -> None:
        self._exists = exists
        self._foreground = foreground
        self._maximized = maximized
        self._minimized = minimized

    def exists(self, timeout: float = 0.0) -> bool:
        return self._exists

    def is_visible(self) -> bool:
        return self._exists

    def has_focus(self) -> bool:
        return self._foreground

    def is_maximized(self) -> bool:
        return self._maximized

    def is_minimized(self) -> bool:
        return self._minimized

    def maximize(self) -> None:
        self._maximized = True

    def set_focus(self) -> None:
        self._foreground = True

    def restore(self) -> None:
        self._minimized = False

    def window_text(self) -> str:
        return "Target App"

    def descendants(self):
        return [FakeElement("ALERT"), FakeElement("Other")]


def test_scan_requires_foreground_and_maximized(monkeypatch: pytest.MonkeyPatch) -> None:
    detector = WindowTextDetector("APP")
    monkeypatch.setattr(detector, "_get_window", lambda: FakeWindow())

    matches = detector.find_matches("ALERT")
    assert matches == ["ALERT"]


def test_scan_rejects_background_window(monkeypatch: pytest.MonkeyPatch) -> None:
    detector = WindowTextDetector("APP")
    monkeypatch.setattr(
        detector,
        "_get_window",
        lambda: FakeWindow(foreground=False),
    )

    matches = detector.find_matches("ALERT")
    assert matches == ["ALERT"]


def test_scan_rejects_non_maximized_window(monkeypatch: pytest.MonkeyPatch) -> None:
    detector = WindowTextDetector("APP")
    monkeypatch.setattr(
        detector,
        "_get_window",
        lambda: FakeWindow(maximized=False),
    )

    matches = detector.find_matches("ALERT")
    assert matches == ["ALERT"]


def test_scan_rejects_missing_window(monkeypatch: pytest.MonkeyPatch) -> None:
    detector = WindowTextDetector("APP")
    monkeypatch.setattr(detector, "_get_window", lambda: FakeWindow(exists=False))

    with pytest.raises(WindowUnavailableError, match="not found"):
        detector.find_matches("ALERT")


def test_scan_restores_minimized_window(monkeypatch: pytest.MonkeyPatch) -> None:
    detector = WindowTextDetector("APP")
    monkeypatch.setattr(
        detector,
        "_get_window",
        lambda: FakeWindow(foreground=False, maximized=False, minimized=True),
    )

    matches = detector.find_matches("ALERT")
    assert matches == ["ALERT"]
