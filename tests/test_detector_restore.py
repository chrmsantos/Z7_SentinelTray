import pytest

from z7_sentineltray.detector import WindowTextDetector, WindowUnavailableError


class _FakeWindow:
    def __init__(self, *, minimized: bool, maximized: bool, focused: bool = True) -> None:
        self._minimized = minimized
        self._maximized = maximized
        self._focused = focused
        self.restore_called = False
        self.maximize_called = False
        self.handle = None

    def is_minimized(self) -> bool:
        return self._minimized

    def is_maximized(self) -> bool:
        return self._maximized

    def has_focus(self) -> bool:
        return self._focused

    def is_active(self) -> bool:
        return self._focused

    def restore(self) -> None:
        self.restore_called = True
        self._minimized = False

    def maximize(self) -> None:
        self.maximize_called = True
        self._maximized = True


def test_restore_attempted_when_not_maximized(monkeypatch: pytest.MonkeyPatch) -> None:
    detector = WindowTextDetector("APP", allow_window_restore=True)
    window = _FakeWindow(minimized=False, maximized=False)

    monkeypatch.setattr(detector, "_show_window", lambda *_args, **_kwargs: None)

    detector._ensure_foreground_and_maximized(window)

    assert window.restore_called is True
    assert window.maximize_called is True


def test_minimized_window_blocks_when_restore_disabled() -> None:
    detector = WindowTextDetector("APP", allow_window_restore=False)
    window = _FakeWindow(minimized=True, maximized=False)

    with pytest.raises(WindowUnavailableError, match="restore disabled"):
        detector._ensure_foreground_and_maximized(window)
