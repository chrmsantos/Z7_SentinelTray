"""Win32 idle-time helpers for detecting user inactivity."""

from __future__ import annotations

import sys


_last_known_real_input_tick: int | None = None
_last_seen_input_tick: int | None = None
_last_seen_input_tick_before_scan: int | None = None


def _get_raw_last_input_tick() -> int | None:
    if sys.platform != "win32":
        return None
    import ctypes

    class _LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

    lii = _LASTINPUTINFO()
    lii.cbSize = ctypes.sizeof(_LASTINPUTINFO)
    if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):  # type: ignore[attr-defined]
        return int(lii.dwTime)
    return None


def _initialize_if_needed() -> None:
    global _last_known_real_input_tick, _last_seen_input_tick
    if _last_seen_input_tick is None:
        raw = _get_raw_last_input_tick()
        if raw is not None:
            _last_seen_input_tick = raw
            _last_known_real_input_tick = raw


def start_scan() -> None:
    """Prepare idle-time tracking before executing a monitor scan."""
    if sys.platform != "win32":
        return
    _initialize_if_needed()
    raw = _get_raw_last_input_tick()
    if raw is not None:
        global _last_known_real_input_tick, _last_seen_input_tick, _last_seen_input_tick_before_scan
        if raw != _last_seen_input_tick:
            _last_known_real_input_tick = raw
            _last_seen_input_tick = raw
        _last_seen_input_tick_before_scan = raw


def end_scan() -> None:
    """Finalize idle-time tracking after executing a monitor scan, ignoring simulated resets."""
    if sys.platform != "win32":
        return
    _initialize_if_needed()
    raw = _get_raw_last_input_tick()
    if raw is not None:
        global _last_seen_input_tick, _last_seen_input_tick_before_scan
        if _last_seen_input_tick_before_scan is not None and raw != _last_seen_input_tick_before_scan:
            # Last input tick changed during the scan. This is simulated input, ignore it
            # for active monitoring threshold purposes but record it as seen.
            _last_seen_input_tick = raw


def get_idle_seconds() -> float:
    """Return seconds elapsed since the last keyboard or mouse input.

    Uses GetLastInputInfo on Windows.  Returns ``float('inf')`` on
    non-Windows platforms or when the Win32 call fails, so callers that
    compare against a threshold will never pause on unsupported platforms.
    """
    if sys.platform != "win32":
        return float("inf")

    _initialize_if_needed()
    raw = _get_raw_last_input_tick()
    if raw is None:
        return float("inf")

    global _last_known_real_input_tick, _last_seen_input_tick
    if raw != _last_seen_input_tick:
        # A new input tick was registered outside of the scan window (real user input)
        _last_known_real_input_tick = raw
        _last_seen_input_tick = raw

    import ctypes
    tick_count: int = ctypes.windll.kernel32.GetTickCount()  # type: ignore[attr-defined]
    if _last_known_real_input_tick is not None:
        idle_ms = (tick_count - _last_known_real_input_tick) & 0xFFFFFFFF
        return idle_ms / 1000.0
    return float("inf")



def is_screen_locked() -> bool:
    """Return True if the Windows screen/workstation is locked."""
    if sys.platform != "win32":
        return False

    import ctypes
    user32 = ctypes.windll.user32
    h_desktop = user32.OpenDesktopW("default", 0, False, 0x0100)
    if h_desktop == 0:
        return True
    try:
        result = user32.SwitchDesktop(h_desktop)
        return result == 0
    finally:
        user32.CloseDesktop(h_desktop)

