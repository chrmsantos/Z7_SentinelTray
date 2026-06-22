import pytest

pywinauto = pytest.importorskip("pywinauto")

from z7_sentineltray.detector import WindowTextDetector  # noqa: E402


def test_prepare_window_restores_minimized(monkeypatch) -> None:
    calls: list[str] = []

    class FakeWindow:
        def __init__(self) -> None:
            self._minimized = True
            self._maximized = False
            self._focused = False

        def exists(self, timeout: int = 0) -> bool:
            return True

        def is_minimized(self) -> bool:
            return self._minimized

        def is_maximized(self) -> bool:
            return self._maximized

        def restore(self) -> None:
            self._minimized = False
            calls.append("restore")

        def maximize(self) -> None:
            self._maximized = True
            calls.append("maximize")

        def set_focus(self) -> None:
            self._focused = True
            calls.append("focus")

        def has_focus(self) -> bool:
            return self._focused

        def wait(self, *_args, **_kwargs) -> None:
            return None

        def is_enabled(self) -> bool:
            return True

        def descendants(self):
            return []

    detector = WindowTextDetector("APP", allow_window_restore=True)
    window = FakeWindow()
    detector._ensure_foreground_and_maximized(window)

    assert "restore" in calls
    assert "focus" in calls
    assert "maximize" in calls


def test_find_matches_accent_insensitive(monkeypatch) -> None:
    detector = WindowTextDetector("APP", allow_window_restore=True)
    monkeypatch.setattr(
        detector,
        "_iter_texts",
        lambda: ["Café closed", "Résumé approved", "No alert"],
    )

    assert detector.find_matches("Cafe") == ["Café closed"]
    assert detector.find_matches("Resume") == ["Résumé approved"]


def test_find_matches_partial_text(monkeypatch) -> None:
    detector = WindowTextDetector("APP", allow_window_restore=True)
    monkeypatch.setattr(
        detector,
        "_iter_texts",
        lambda: ["Primary system error", "All good"],
    )

    assert detector.find_matches("error") == ["Primary system error"]


def test_find_matches_case_insensitive(monkeypatch) -> None:
    detector = WindowTextDetector("APP", allow_window_restore=True)
    monkeypatch.setattr(
        detector,
        "_iter_texts",
        lambda: ["Process completed", "Critical alert"],
    )

    assert detector.find_matches("alert") == ["Critical alert"]


def test_get_window_resolves_ambiguous(monkeypatch) -> None:
    class FakeWindow:
        def __init__(self, focus: bool, visible: bool, enabled: bool, title: str) -> None:
            self._focus = focus
            self._visible = visible
            self._enabled = enabled
            self._title = title

        def has_focus(self) -> bool:
            return self._focus

        def is_visible(self) -> bool:
            return self._visible

        def is_enabled(self) -> bool:
            return self._enabled

        def window_text(self) -> str:
            return self._title

    class FakeDesktop:
        def __init__(self, *args, **kwargs) -> None:
            return None

        def windows(self, *_args, **_kwargs):
            return [
                FakeWindow(False, True, True, "APP Monitor"),
                FakeWindow(True, True, True, "APP Monitor 2"),
            ]

    detector = WindowTextDetector("APP", allow_window_restore=True)
    monkeypatch.setattr("z7_sentineltray.detector.Desktop", FakeDesktop)

    window = detector._get_window()

    assert isinstance(window, FakeWindow)
    assert window.has_focus()


def test_get_window_matches_partial_title(monkeypatch) -> None:
    class FakeWindow:
        def __init__(self, title: str) -> None:
            self._title = title

        def window_text(self) -> str:
            return self._title

        def has_focus(self) -> bool:
            return True

        def is_visible(self) -> bool:
            return True

        def is_enabled(self) -> bool:
            return True

    class FakeDesktop:
        def __init__(self, *args, **kwargs) -> None:
            return None

        def windows(self, *_args, **_kwargs):
            return [FakeWindow("Main Application - Monitor")]

    detector = WindowTextDetector("Monitor", allow_window_restore=True)
    monkeypatch.setattr("z7_sentineltray.detector.Desktop", FakeDesktop)

    window = detector._get_window()

    assert isinstance(window, FakeWindow)


def test_list_matching_window_titles(monkeypatch) -> None:
    class FakeWindow:
        def __init__(self, title: str) -> None:
            self._title = title

        def window_text(self) -> str:
            return self._title

    class FakeDesktop:
        def __init__(self, *args, **kwargs) -> None:
            return None

        def windows(self, *_args, **_kwargs):
            return [
                FakeWindow("Alpha"),
                FakeWindow("Main Monitor"),
                FakeWindow("Monitor - Secondary"),
            ]

    detector = WindowTextDetector("Monitor", allow_window_restore=True)
    monkeypatch.setattr("z7_sentineltray.detector.Desktop", FakeDesktop)

    titles = detector.list_matching_window_titles()

    assert titles == ["Main Monitor", "Monitor - Secondary"]


def test_prepare_window_visibility_timeout_accepts_visible() -> None:
    class FakeWindow:
        def exists(self, timeout: int = 0) -> bool:
            return False

        def is_minimized(self) -> bool:
            return False

        def is_visible(self) -> bool:
            return True

    detector = WindowTextDetector("APP", allow_window_restore=True)
    window = FakeWindow()

    assert detector._window_exists(window, timeout=1.0) is True


def test_window_is_minimized_handles_missing_attrs() -> None:
    detector = WindowTextDetector("APP", allow_window_restore=True)

    class FakeWindow:
        pass

    assert detector._window_is_minimized(FakeWindow()) is False


# ---------------------------------------------------------------------------
# Non-intrusive scan tests: window state is restored after reading
# ---------------------------------------------------------------------------


class _MinimizableWindow:
    """Fake window that starts minimized and tracks state changes."""

    def __init__(self) -> None:
        self._minimized = True
        self._maximized = False
        self._focused = False
        self.handle = 9999

    def exists(self, timeout: float = 0.0) -> bool:
        return True

    def is_minimized(self) -> bool:
        return self._minimized

    def is_maximized(self) -> bool:
        return self._maximized

    def is_visible(self) -> bool:
        return True

    def has_focus(self) -> bool:
        return self._focused

    def restore(self) -> None:
        self._minimized = False

    def maximize(self) -> None:
        self._maximized = True

    def set_focus(self) -> None:
        self._focused = True

    def window_text(self) -> str:
        return "App"

    def descendants(self):
        return []


def test_iter_texts_minimizes_window_back_after_scan(monkeypatch) -> None:
    """A window that was minimized must be minimized again after the scan."""
    fake_window = _MinimizableWindow()
    detector = WindowTextDetector("App", allow_window_restore=True)
    monkeypatch.setattr(detector, "_get_window", lambda: fake_window)
    monkeypatch.setattr(detector, "_get_foreground_handle", lambda: 1234)

    minimize_calls: list[tuple[int, int]] = []

    def fake_show_window(handle: int, cmd: int) -> None:
        minimize_calls.append((handle, cmd))
        if cmd == 6:
            fake_window._minimized = True

    monkeypatch.setattr(detector, "_show_window", fake_show_window)

    restored: list[int | None] = []
    monkeypatch.setattr(
        detector,
        "_restore_prior_foreground",
        lambda h: restored.append(h),
    )

    detector._iter_texts()

    assert any(cmd == 6 for _h, cmd in minimize_calls), "SW_MINIMIZE must be issued"
    assert fake_window._minimized, "Window must end up minimized"
    assert restored == [1234], "Prior foreground must be restored"


def test_iter_texts_restores_foreground_when_not_minimized(monkeypatch) -> None:
    """When the window was already visible, only the foreground is restored."""
    fake_window = _MinimizableWindow()
    fake_window._minimized = False
    fake_window._maximized = True
    fake_window._focused = True

    detector = WindowTextDetector("App", allow_window_restore=True)
    monkeypatch.setattr(detector, "_get_window", lambda: fake_window)
    monkeypatch.setattr(detector, "_get_foreground_handle", lambda: 5678)

    minimize_calls: list[tuple[int, int]] = []
    monkeypatch.setattr(
        detector,
        "_show_window",
        lambda h, cmd: minimize_calls.append((h, cmd)),
    )

    restored: list[int | None] = []
    monkeypatch.setattr(
        detector,
        "_restore_prior_foreground",
        lambda h: restored.append(h),
    )

    detector._iter_texts()

    assert not any(cmd == 6 for _h, cmd in minimize_calls), "SW_MINIMIZE must NOT be issued"
    assert restored == [5678], "Prior foreground must still be restored"
