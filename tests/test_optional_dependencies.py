from __future__ import annotations

import pytest

from z7_sentineltray import detector as detector_module
from z7_sentineltray.detector import WindowTextDetector


def test_detector_requires_pywinauto_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(detector_module, "Desktop", None)
    detector = WindowTextDetector("APP")
    with pytest.raises(RuntimeError, match="pywinauto is required"):
        detector._get_window()
