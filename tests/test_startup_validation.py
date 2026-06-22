from z7_sentineltray.detector import WindowTextDetector, WindowUnavailableError


def test_check_ready_raises_when_missing(monkeypatch) -> None:
    detector = WindowTextDetector("APP")

    class FakeWindow:
        def exists(self, timeout: float = 0.0) -> bool:
            return False

    monkeypatch.setattr(detector, "_get_window", lambda: FakeWindow())

    try:
        detector.check_ready()
    except WindowUnavailableError:
        return
    raise AssertionError("Expected WindowUnavailableError")
