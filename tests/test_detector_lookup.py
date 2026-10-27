from __future__ import annotations

import pytest

from z7_sentineltray.detector import WindowTextDetector


class FakeWindow:
    def __init__(
        self,
        title: str,
        *,
        handle: int | None = None,
        visible: bool = True,
        minimized: bool = False,
        text_error: Exception | None = None,
    ) -> None:
        self.handle = handle
        self._title = title
        self._visible = visible
        self._minimized = minimized
        self._text_error = text_error

    def window_text(self) -> str:
        if self._text_error is not None:
            raise self._text_error
        return self._title

    def is_minimized(self) -> bool:
        return self._minimized

    def is_visible(self) -> bool:
        return self._visible


class FakeElement:
    def __init__(self, text: str) -> None:
        self._text = text

    def window_text(self) -> str:
        return self._text


def _desktop_factory(windows_by_backend: dict[str, list[object]]):
    class _FakeDesktop:
        def __init__(self, *args, **kwargs) -> None:
            self._backend = kwargs.get("backend")

        def windows(self, *args, **kwargs):
            return list(windows_by_backend.get(self._backend, []))

    return _FakeDesktop


def test_collect_candidates_falls_back_to_win32_backend(monkeypatch: pytest.MonkeyPatch):
    """When UIA drops the busy target window, the win32 backend must still find it."""
    window = FakeWindow("Sino.Siscam - Main")
    monkeypatch.setattr(
        "z7_sentineltray.detector.Desktop",
        _desktop_factory({"uia": [], "win32": [window]}),
    )
    detector = WindowTextDetector(r"Sino\.Siscam")

    assert detector._collect_candidate_windows() == [window]


def test_collect_candidates_falls_back_when_backend_raises(monkeypatch: pytest.MonkeyPatch):
    """A failing UIA enumeration must not abort the lookup."""
    window = FakeWindow("Sino.Siscam - Main")

    class _BrokenDesktop:
        def __init__(self, *args, **kwargs) -> None:
            self._backend = kwargs.get("backend")

        def windows(self, *args, **kwargs):
            if self._backend == "uia":
                raise RuntimeError("UIA provider hung")
            return [window]

    monkeypatch.setattr("z7_sentineltray.detector.Desktop", _BrokenDesktop)
    detector = WindowTextDetector(r"Sino\.Siscam")

    assert detector._collect_candidate_windows() == [window]


def test_collect_candidates_uses_win32_title_fallback(monkeypatch: pytest.MonkeyPatch):
    """Busy targets make window_text() fail; the cached Win32 caption must be used."""
    window = FakeWindow(
        "",
        handle=4242,
        text_error=RuntimeError("target UI thread is busy"),
    )
    monkeypatch.setattr(
        "z7_sentineltray.detector.Desktop",
        _desktop_factory({"uia": [window]}),
    )
    detector = WindowTextDetector(r"Sino\.Siscam")
    monkeypatch.setattr(
        detector,
        "_win32_get_window_text",
        lambda handle: "Sino.Siscam - Main" if handle == 4242 else "",
    )
    monkeypatch.setattr(detector, "_win32_is_window_visible", lambda handle: True)

    assert detector._collect_candidate_windows() == [window]


def test_collect_candidates_ignore_hidden_helper_windows(monkeypatch: pytest.MonkeyPatch):
    """Hidden helper windows sharing the title must not be selected."""
    window = FakeWindow("Sino.Siscam helper", handle=1)
    monkeypatch.setattr(
        "z7_sentineltray.detector.Desktop",
        _desktop_factory({"uia": [window]}),
    )
    detector = WindowTextDetector(r"Sino\.Siscam")
    monkeypatch.setattr(detector, "_win32_is_window_visible", lambda handle: False)

    assert detector._collect_candidate_windows() == []


def test_collect_candidates_keep_minimized_windows(monkeypatch: pytest.MonkeyPatch):
    """Minimized windows report IsOffscreen to UIA but keep WS_VISIBLE and must match."""
    window = FakeWindow("Sino.Siscam - Main", handle=7, visible=False, minimized=True)
    monkeypatch.setattr(
        "z7_sentineltray.detector.Desktop",
        _desktop_factory({"uia": [window]}),
    )
    detector = WindowTextDetector(r"Sino\.Siscam")
    monkeypatch.setattr(detector, "_win32_is_window_visible", lambda handle: True)

    assert detector._collect_candidate_windows() == [window]


def test_title_match_is_case_insensitive(monkeypatch: pytest.MonkeyPatch):
    window = FakeWindow("SINO.SISCAM v2 - Monitor")
    monkeypatch.setattr(
        "z7_sentineltray.detector.Desktop",
        _desktop_factory({"uia": [window]}),
    )
    detector = WindowTextDetector(r"sino\.siscam")

    assert detector._collect_candidate_windows() == [window]


def test_title_match_is_accent_insensitive(monkeypatch: pytest.MonkeyPatch):
    window = FakeWindow("Configuração do Siscam")
    monkeypatch.setattr(
        "z7_sentineltray.detector.Desktop",
        _desktop_factory({"uia": [window]}),
    )
    detector = WindowTextDetector("configuracao")

    assert detector._collect_candidate_windows() == [window]


class _BusyWindow:
    handle = 4242

    def is_minimized(self) -> bool:
        raise RuntimeError("target UI thread is busy")

    def is_visible(self) -> bool:
        raise RuntimeError("target UI thread is busy")


def test_window_exists_uses_win32_handle_when_automation_fails(
    monkeypatch: pytest.MonkeyPatch,
):
    """Busy targets make UIA visibility checks raise; the Win32 handle check must win."""
    detector = WindowTextDetector("APP")
    monkeypatch.setattr(detector, "_win32_is_window_visible", lambda handle: True)

    assert detector._window_exists(_BusyWindow(), timeout=1.0) is True


def test_window_exists_false_when_hidden_and_automation_raises(
    monkeypatch: pytest.MonkeyPatch,
):
    detector = WindowTextDetector("APP")
    monkeypatch.setattr(detector, "_win32_is_window_visible", lambda handle: False)

    assert detector._window_exists(_BusyWindow(), timeout=1.0) is False


def test_get_window_invalidates_stale_cached_window(monkeypatch: pytest.MonkeyPatch):
    stale = FakeWindow("Sino.Siscam - Main", handle=1)
    fresh = FakeWindow("Sino.Siscam - Main", handle=2)
    detector = WindowTextDetector(r"Sino\.Siscam")
    detector._last_window = stale
    monkeypatch.setattr(detector, "_window_exists", lambda window, timeout=0.0: window is fresh)
    monkeypatch.setattr(detector, "_win32_is_window_visible", lambda handle: True)
    monkeypatch.setattr(
        "z7_sentineltray.detector.Desktop",
        _desktop_factory({"uia": [fresh]}),
    )

    assert detector._get_window() is fresh


def test_iter_texts_falls_back_to_win32_descendants(monkeypatch: pytest.MonkeyPatch):
    """A failing UIA descendant read must fall back instead of erroring the scan."""

    class FlakyWindow(FakeWindow):
        def descendants(self):
            raise RuntimeError("target UI thread is busy")

        def exists(self, timeout: float = 0.0) -> bool:
            return True

        def is_maximized(self) -> bool:
            return True

        def has_focus(self) -> bool:
            return True

    window = FlakyWindow("Sino.Siscam - Main", handle=7)
    detector = WindowTextDetector(r"Sino\.Siscam")
    monkeypatch.setattr(detector, "_get_window", lambda: window)
    monkeypatch.setattr(detector, "_get_foreground_handle", lambda: None)
    monkeypatch.setattr(
        detector, "_win32_descendants", lambda _window, _cause: [FakeElement("ALERT 42")]
    )

    texts = detector._iter_texts()

    assert "Sino.Siscam - Main" in texts
    assert "ALERT 42" in texts
