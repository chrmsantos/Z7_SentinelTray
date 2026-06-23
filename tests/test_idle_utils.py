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


def test_get_idle_seconds_simulation_isolation(monkeypatch: pytest.MonkeyPatch) -> None:
    import ctypes
    import z7_sentineltray.idle_utils as idle_utils

    # Reset state
    idle_utils._last_known_real_input_tick = None
    idle_utils._last_seen_input_tick = None
    idle_utils._last_seen_input_tick_before_scan = None

    # Mock platform and raw tick functions
    monkeypatch.setattr(sys, "platform", "win32")

    current_raw_last_input_tick = 10000
    current_tick_count = 20000

    def mock_raw_last_input_tick():
        return current_raw_last_input_tick

    def mock_get_tick_count():
        return current_tick_count

    monkeypatch.setattr(idle_utils, "_get_raw_last_input_tick", mock_raw_last_input_tick)
    monkeypatch.setattr(ctypes.windll.kernel32, "GetTickCount", mock_get_tick_count)

    # 1. Initially (before any scan), the idle time is current_tick - last_input
    # 20000 - 10000 = 10000 ms = 10.0 seconds
    assert idle_utils.get_idle_seconds() == 10.0

    # 2. Start a scan.
    idle_utils.start_scan()
    # At start_scan, raw tick is still 10000.

    # 3. During the scan, simulation/OS resets the idle timer to 20100 (closer to current time)
    current_raw_last_input_tick = 20100
    current_tick_count = 20200  # scan finishes at 20200

    # 4. End the scan.
    idle_utils.end_scan()

    # 5. In get_idle_seconds(), we check the idle time.
    # The tick count is 20300.
    current_tick_count = 20300
    # Even though current_raw_last_input_tick is 20100 (simulated input),
    # the idle_utils should ignore it and calculate idle time based on the last known real input (10000).
    # Expected idle time: 20300 - 10000 = 10300 ms = 10.3 seconds.
    assert idle_utils.get_idle_seconds() == 10.3

    # 6. Now a real user input happens outside of a scan (at tick 20400).
    current_raw_last_input_tick = 20400
    current_tick_count = 20500
    # Expected idle time: 20500 - 20400 = 100 ms = 0.1 seconds.
    assert idle_utils.get_idle_seconds() == 0.1

