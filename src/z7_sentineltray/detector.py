"""Win32 window-text detection using pywinauto automation."""

from __future__ import annotations

import ctypes
import logging
import re
import time
import unicodedata

try:
    from pywinauto import Desktop
    from pywinauto.findwindows import ElementAmbiguousError

    _PYWINAUTO_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - optional dependency
    Desktop = None  # type: ignore[assignment]

    class ElementAmbiguousError(RuntimeError):
        """Fallback error when pywinauto is unavailable."""

    _PYWINAUTO_IMPORT_ERROR = exc

LOGGER = logging.getLogger(__name__)

# Win32 window class names for Windows Shell overlays that grab the foreground
# and block SetForegroundWindow from succeeding while they are open.
_SHELL_OVERLAY_CLASSES = frozenset(
    {
        "Windows.UI.Core.CoreWindow",  # Start menu host (Windows 10/11)
        "Shell_TrayWnd",  # Taskbar
        "Shell_SecondaryTrayWnd",  # Secondary-monitor taskbar
        "NotifyIconOverflowWindow",  # System tray overflow
    }
)


class WindowUnavailableError(RuntimeError):
    """Raised when the target window is temporarily unavailable or disabled."""


class WindowTextDetector:
    """Detects and reads text from a Win32 window matched by title regex."""

    def __init__(
        self,
        window_title_regex: str,
        allow_window_restore: bool = True,
        log_throttle_seconds: int = 60,
    ) -> None:
        self._window_title_regex = re.compile(window_title_regex)
        self._allow_window_restore = allow_window_restore
        self._last_window = None
        self._log_throttle_seconds = max(0, log_throttle_seconds)
        self._last_log: dict[str, float] = {}
        self._phrase_regex_cache: str | None = None
        self._phrase_pattern_cache: re.Pattern[str] | None = None

    @staticmethod
    def _normalize_text(value: str) -> str:
        decomposed = unicodedata.normalize("NFKD", value)
        return "".join([ch for ch in decomposed if not unicodedata.combining(ch)])

    def _log_throttled(self, level: int, key: str, message: str, *args: object) -> None:
        if self._log_throttle_seconds == 0:
            LOGGER.log(level, message, *args, extra={"category": "scan"})
            return
        now = time.monotonic()
        last = self._last_log.get(key, 0.0)
        if now - last >= self._log_throttle_seconds:
            self._last_log[key] = now
            LOGGER.log(level, message, *args, extra={"category": "scan"})

    def _window_exists(self, window: object, timeout: float = 0.0) -> bool:
        try:
            if hasattr(window, "exists") and window.exists(timeout=timeout):
                return True
            if self._window_is_minimized(window):
                return True
            if hasattr(window, "is_visible"):
                return window.is_visible()
        except Exception:
            return False
        else:
            return True

    def _window_is_foreground(self, window: object) -> bool:
        try:
            if hasattr(window, "has_focus") and window.has_focus():
                return True
        except Exception:
            return False
        try:
            if hasattr(window, "is_active") and window.is_active():
                return True
        except Exception:
            return False
        try:
            if hasattr(window, "handle"):
                handle = window.handle
                if handle:
                    return ctypes.windll.user32.GetForegroundWindow() == handle
        except Exception:
            return False
        return False

    def _window_is_maximized(self, window: object) -> bool:
        try:
            if hasattr(window, "is_maximized"):
                return bool(window.is_maximized())
        except Exception:
            return False
        try:
            if hasattr(window, "handle"):
                handle = window.handle
                if handle:
                    return bool(ctypes.windll.user32.IsZoomed(handle))
        except Exception:
            return False
        return False

    def _window_is_minimized(self, window: object) -> bool:
        try:
            if hasattr(window, "is_minimized"):
                return bool(window.is_minimized())
        except Exception:
            return False
        try:
            if hasattr(window, "handle"):
                handle = window.handle
                if handle:
                    return bool(ctypes.windll.user32.IsIconic(handle))
        except Exception:
            return False
        return False

    def _force_foreground(self, window: object) -> None:
        try:
            if hasattr(window, "set_focus"):
                window.set_focus()
        except Exception:
            LOGGER.debug("Failed to set focus", exc_info=True)
        try:
            if not hasattr(window, "handle"):
                return
            handle = window.handle
            if not handle:
                return
            user32 = ctypes.windll.user32
            user32.ShowWindow(handle, 3)
            user32.BringWindowToTop(handle)
            user32.SetForegroundWindow(handle)
            user32.SetWindowPos(handle, -1, 0, 0, 0, 0, 0x0001 | 0x0002)
            user32.SetWindowPos(handle, -2, 0, 0, 0, 0, 0x0001 | 0x0002)
        except Exception:
            LOGGER.debug("Failed to force window foreground", exc_info=True)

    def _show_window(self, handle: int, command: int) -> None:
        ctypes.windll.user32.ShowWindow(handle, command)

    def _restore_window(self, window: object) -> None:
        try:
            if hasattr(window, "restore"):
                window.restore()
        except Exception:
            LOGGER.debug("Failed to restore window", exc_info=True)
        try:
            if hasattr(window, "handle"):
                handle = window.handle
                if handle:
                    self._show_window(handle, 9)
        except Exception:
            LOGGER.debug("Failed to restore window via handle", exc_info=True)

    def _get_foreground_handle(self) -> int | None:
        """Return the Win32 handle of the current foreground window."""
        try:
            handle = ctypes.windll.user32.GetForegroundWindow()
            return int(handle) if handle else None
        except Exception:
            return None

    def _minimize_window(self, window: object) -> None:
        """Minimize *window* without activating another window (SW_MINIMIZE=6)."""
        try:
            if hasattr(window, "handle"):
                handle = window.handle
                if handle:
                    self._show_window(handle, 6)
                    return
        except Exception:
            LOGGER.debug("Failed to minimize window via handle", exc_info=True)
        try:
            if hasattr(window, "minimize"):
                window.minimize()
        except Exception:
            LOGGER.debug("Failed to minimize window via pywinauto", exc_info=True)

    def _restore_prior_foreground(self, handle: int | None) -> None:
        """Set focus back to the window that was active before the scan."""
        if not handle:
            return
        try:
            ctypes.windll.user32.SetForegroundWindow(handle)
        except Exception:
            LOGGER.debug("Failed to restore prior foreground window", exc_info=True)

    def _get_foreground_class(self) -> str:
        """Return the Win32 class name of the current foreground window."""
        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            if not hwnd:
                return ""
            buf = ctypes.create_unicode_buffer(256)
            ctypes.windll.user32.GetClassNameW(hwnd, buf, 256)
        except Exception:
            return ""
        else:
            return buf.value

    def _dismiss_shell_overlay(self) -> bool:
        """Send Escape to dismiss a shell overlay (e.g. Start menu) blocking the foreground.

        Returns True if an overlay was detected and Escape was sent.
        """
        class_name = self._get_foreground_class()
        if class_name not in _SHELL_OVERLAY_CLASSES:
            return False
        try:
            _VK_ESCAPE = 0x1B  # noqa: N806
            _KEYEVENTF_KEYUP = 0x0002  # noqa: N806
            ctypes.windll.user32.keybd_event(_VK_ESCAPE, 0, 0, 0)
            ctypes.windll.user32.keybd_event(_VK_ESCAPE, 0, _KEYEVENTF_KEYUP, 0)
            time.sleep(0.3)
            LOGGER.debug("Dismissed shell overlay: %s", class_name, extra={"category": "scan"})
        except Exception:
            LOGGER.debug("Failed to dismiss shell overlay", exc_info=True)
            return False
        else:
            return True

    def _ensure_foreground_and_maximized(self, window: object) -> None:  # noqa: C901
        if self._window_is_minimized(window):
            if not self._allow_window_restore:
                raise WindowUnavailableError("Target window minimized; restore disabled")
            self._restore_window(window)
        elif self._allow_window_restore and not self._window_is_maximized(window):
            self._restore_window(window)
        if not self._window_is_foreground(window):
            self._force_foreground(window)
        if not self._window_is_maximized(window):
            if not self._allow_window_restore:
                raise WindowUnavailableError("Target window not maximized; restore disabled")
            try:
                if hasattr(window, "maximize"):
                    window.maximize()
            except Exception:
                LOGGER.debug("Failed to maximize window", exc_info=True)
            try:
                if hasattr(window, "handle"):
                    handle = window.handle
                    if handle:
                        self._show_window(handle, 3)
            except Exception:
                LOGGER.debug("Failed to maximize window via handle", exc_info=True)
        if not self._window_is_foreground(window):
            raise WindowUnavailableError("Target window not in foreground")
        if not self._window_is_maximized(window):
            raise WindowUnavailableError("Target window not maximized")

    def _select_best_window(self, candidates: list[object]) -> object:
        if not candidates:
            raise ElementAmbiguousError("No window candidates available")

        def score(window: object) -> int:
            value = 0
            try:
                if hasattr(window, "has_focus") and window.has_focus():
                    value += 3
            except Exception:
                pass
            try:
                if hasattr(window, "is_visible") and window.is_visible():
                    value += 2
            except Exception:
                pass
            try:
                if hasattr(window, "is_enabled") and window.is_enabled():
                    value += 1
            except Exception:
                pass
            return value

        selected = max(candidates, key=score)
        LOGGER.info(
            "Multiple windows matched; selecting best candidate (%s found)",
            len(candidates),
            extra={"category": "scan"},
        )
        return selected

    def _collect_candidate_windows(self) -> list[object]:
        if Desktop is None:
            raise RuntimeError(
                "pywinauto is required for window detection. "
                "Install dependencies from requirements.txt."
            ) from _PYWINAUTO_IMPORT_ERROR
        desktop = Desktop(backend="uia")
        candidates: list[object] = []
        for window in desktop.windows():
            try:
                title_text = window.window_text()
            except Exception:
                continue
            if not title_text:
                continue
            if self._window_title_regex.search(title_text):
                candidates.append(window)
        return candidates

    def _get_window(self) -> object:
        if Desktop is None:
            raise RuntimeError(
                "pywinauto is required for window detection. "
                "Install dependencies from requirements.txt."
            ) from _PYWINAUTO_IMPORT_ERROR
        if self._last_window is not None:
            try:
                if hasattr(self._last_window, "exists"):
                    if self._last_window.exists(timeout=0.5):
                        return self._last_window
                else:
                    return self._last_window
            except Exception:
                self._last_window = None
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                candidates = self._collect_candidate_windows()
                if not candidates:
                    raise WindowUnavailableError("Target window not found")
                if len(candidates) == 1:
                    self._last_window = candidates[0]
                    return candidates[0]
                window = self._select_best_window(candidates)
                self._last_window = window
            except Exception as exc:
                last_exc = exc
                self._log_throttled(
                    logging.WARNING,
                    "window_lookup_failed",
                    "Window lookup failed (attempt %s/3): %s",
                    attempt + 1,
                    exc,
                )
                time.sleep(0.5 * (2**attempt))
            else:
                return window
        if isinstance(last_exc, WindowUnavailableError):
            raise last_exc
        raise WindowUnavailableError("Target window lookup failed") from last_exc

    def list_matching_window_titles(self) -> list[str]:
        """Return window titles matching the configured title regex."""
        candidates = self._collect_candidate_windows()
        titles: list[str] = []
        for window in candidates:
            try:
                title_text = window.window_text()
            except Exception:
                continue
            if title_text:
                titles.append(title_text)
        return titles

    def check_ready(self) -> None:
        """Raise ``WindowUnavailableError`` if the target window cannot be activated."""
        window = self._get_window()
        if not self._window_exists(window, timeout=1.0):
            raise WindowUnavailableError("Target window not found")
        self._ensure_foreground_and_maximized(window)

    def _iter_texts(self) -> list[str]:
        window = self._get_window()
        if not self._window_exists(window, timeout=1.0):
            raise WindowUnavailableError("Target window not found")
        was_minimized = self._window_is_minimized(window)
        prior_foreground = self._get_foreground_handle()
        texts: list[str] = []
        try:
            self._ensure_foreground_and_maximized(window)
            try:
                try:
                    if hasattr(window, "window_text"):
                        title_text = window.window_text()
                        if title_text:
                            texts.append(title_text)
                except Exception:
                    LOGGER.debug("Failed to read window title text", exc_info=True)
                for element in window.descendants():
                    try:
                        text = element.window_text()
                    except Exception:
                        continue
                    if text:
                        texts.append(text)
            except Exception as exc:
                raise RuntimeError("Failed to read window texts") from exc
        finally:
            # Non-intrusive: restore the original window state and active focus
            # so the user's workflow is not disrupted by the scan.
            if was_minimized:
                self._minimize_window(window)
            self._restore_prior_foreground(prior_foreground)
        return texts

    def find_matches(self, phrase_regex: str) -> list[str]:
        """Return text elements from the target window matching *phrase_regex*."""
        texts = self._iter_texts()
        if not texts:
            return []

        phrase_value = "" if phrase_regex is None else str(phrase_regex)
        if not phrase_value.strip():
            return texts

        normalized_regex = self._normalize_text(phrase_value)
        if normalized_regex != self._phrase_regex_cache or self._phrase_pattern_cache is None:
            try:
                pattern = re.compile(normalized_regex, re.IGNORECASE)
            except re.error as exc:
                raise ValueError("Invalid phrase regex") from exc
            self._phrase_regex_cache = normalized_regex
            self._phrase_pattern_cache = pattern
        pattern = self._phrase_pattern_cache
        matches: list[str] = []
        normalize = self._normalize_text
        for text in texts:
            if pattern.search(normalize(text)):
                matches.append(text)
        return matches
