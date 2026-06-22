from __future__ import annotations

import sys

import pytest

from z7_sentineltray.idle_utils import get_idle_seconds


def test_get_idle_seconds_returns_nonnegative() -> None:
    result = get_idle_seconds()
    assert result >= 0


def test_get_idle_seconds_returns_inf_on_non_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    result = get_idle_seconds()
    assert result == float("inf")
