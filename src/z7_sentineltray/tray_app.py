"""System-tray icon and console-window visibility management."""

from __future__ import annotations

import contextlib
import ctypes
import logging
import math
import threading
from collections.abc import Callable

import pystray  # type: ignore[import]
from PIL import Image, ImageDraw  # type: ignore[import]

LOGGER = logging.getLogger(__name__)

_SW_HIDE = 0
_SW_SHOW = 5


def _make_green_eye(size: int = 64) -> Image.Image:
    """Draw a green eye icon at *size* x *size* using 4x supersampling."""
    scale = 4
    s = size * scale
    cx, cy = s // 2, s // 2

    # Eye-shape bounding box (horizontal lens / almond)
    ew = int(s * 0.88)
    eh = int(s * 0.52)
    ex0, ey0 = cx - ew // 2, cy - eh // 2
    ex1, ey1 = ex0 + ew, ey0 + eh

    # Content layer
    content = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    cd = ImageDraw.Draw(content)

    # Sclera (eye-white)
    cd.ellipse([ex0, ey0, ex1, ey1], fill=(255, 255, 255, 255))

    # Outer iris ring — deep forest green
    iris_r = int(s * 0.21)
    cd.ellipse(
        [cx - iris_r, cy - iris_r, cx + iris_r, cy + iris_r],
        fill=(27, 94, 32, 255),
    )
    # Mid iris — vibrant green
    mid_r = int(s * 0.17)
    cd.ellipse(
        [cx - mid_r, cy - mid_r, cx + mid_r, cy + mid_r],
        fill=(46, 204, 113, 255),
    )
    # Inner iris ring
    inner_r = int(s * 0.13)
    cd.ellipse(
        [cx - inner_r, cy - inner_r, cx + inner_r, cy + inner_r],
        fill=(39, 174, 96, 255),
    )
    # Pupil
    pupil_r = int(s * 0.085)
    cd.ellipse(
        [cx - pupil_r, cy - pupil_r, cx + pupil_r, cy + pupil_r],
        fill=(10, 10, 10, 255),
    )
    # Catchlight highlight
    hl_r = max(3, int(s * 0.038))
    hl_x = cx + int(s * 0.07)
    hl_y = cy - int(s * 0.07)
    cd.ellipse(
        [hl_x - hl_r, hl_y - hl_r, hl_x + hl_r, hl_y + hl_r],
        fill=(255, 255, 255, 255),
    )

    # Alpha mask — only the eye-lens shape is visible
    mask = Image.new("L", (s, s), 0)
    md = ImageDraw.Draw(mask)
    md.ellipse([ex0, ey0, ex1, ey1], fill=255)

    result = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    result.paste(content, mask=mask)

    # Eyelid border
    border = ImageDraw.Draw(result)
    border_w = max(2, int(s * 0.025))
    border.ellipse([ex0, ey0, ex1, ey1], outline=(13, 77, 13, 255), width=border_w)

    # Upper eyelash accent lines
    lash_color = (13, 77, 13, 200)
    lash_len = int(s * 0.07)
    lash_w = max(2, int(s * 0.018))
    for i in range(5):
        angle_deg = 210 + i * 30
        angle_rad = math.radians(angle_deg)
        sx = int(cx + (ew // 2) * math.cos(angle_rad))
        sy = int(cy + (eh // 2) * math.sin(angle_rad))
        ex_end = int(sx + lash_len * math.cos(angle_rad))
        ey_end = int(sy + lash_len * math.sin(angle_rad))
        border.line([sx, sy, ex_end, ey_end], fill=lash_color, width=lash_w)

    return result.resize((size, size), Image.LANCZOS)


def _console_hwnd() -> int:
    try:
        return int(ctypes.windll.kernel32.GetConsoleWindow())  # type: ignore[attr-defined]
    except Exception:
        return 0


def set_console_visible(visible: bool) -> None:
    """Show or hide the Win32 console window attached to this process.

    Args:
        visible: ``True`` to show, ``False`` to hide.
    """
    hwnd = _console_hwnd()
    if not hwnd:
        return
    with contextlib.suppress(Exception):
        ctypes.windll.user32.ShowWindow(hwnd, _SW_SHOW if visible else _SW_HIDE)  # type: ignore[attr-defined]


_CTRL_CLOSE_EVENT = 2
_HandlerRoutine = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_uint)  # type: ignore[attr-defined]


def _install_close_to_tray_handler(tray: TrayIcon) -> object:
    """Register a SetConsoleCtrlHandler that hides the console on [X] instead of terminating."""

    @_HandlerRoutine
    def _handler(ctrl_type: int) -> bool:
        if ctrl_type == _CTRL_CLOSE_EVENT:
            tray._console_visible = False
            set_console_visible(False)
            if tray._icon is not None:
                with contextlib.suppress(Exception):
                    tray._icon.update_menu()
            return True  # suppress default close / terminate
        return False

    try:
        ctypes.windll.kernel32.SetConsoleCtrlHandler(_handler, True)  # type: ignore[attr-defined]
    except Exception as exc:
        LOGGER.debug("SetConsoleCtrlHandler install failed: %s", exc)
    return _handler


class TrayIcon:
    """System-tray icon.

    When *on_open_status* is provided the icon runs in GUI mode:
    the console is kept hidden and the tray menu offers "Open Status"
    as the default (left-click / double-click) action instead of the
    legacy console-toggle.
    """

    def __init__(
        self,
        *,
        on_exit_requested: Callable[[], None],
        on_open_status: Callable[[], None] | None = None,
    ) -> None:
        self._on_exit_requested = on_exit_requested
        self._on_open_status = on_open_status
        self._icon: pystray.Icon | None = None
        self._thread: threading.Thread | None = None
        self._console_visible = on_open_status is None  # hidden in GUI mode
        self._close_handler: object = None

    # ------------------------------------------------------------------
    # Menu callbacks (called from the pystray thread)
    # ------------------------------------------------------------------

    def _console_menu_label(self, item: pystray.MenuItem) -> str:
        return "Fechar Console" if self._console_visible else "Abrir Console"

    def _toggle_console(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        self._console_visible = not self._console_visible
        set_console_visible(self._console_visible)
        icon.update_menu()

    def _open_status(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        if self._on_open_status is not None:
            self._on_open_status()

    def _on_exit(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        # Null _icon immediately so _check_exit / watchdog won't attempt a second stop.
        # The actual icon.stop() is dispatched to a daemon thread to avoid blocking
        # the pystray callback thread (which may be the Win32 WndProc thread).
        icon_ref = self._icon
        self._icon = None
        self._on_exit_requested()
        if icon_ref is not None:
            threading.Thread(
                target=icon_ref.stop, daemon=True, name="tray-exit-stop"
            ).start()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the tray icon."""
        if self._on_open_status is not None:
            # GUI mode — hide console, offer Status as default action
            self._console_visible = False
            set_console_visible(False)
            menu = pystray.Menu(
                pystray.MenuItem(
                    "Abrir Status",
                    self._open_status,
                    default=True,
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Sair", self._on_exit),
            )
        else:
            # Legacy console mode
            self._console_visible = True
            menu = pystray.Menu(
                pystray.MenuItem(self._console_menu_label, self._toggle_console),
                pystray.MenuItem("Sair", self._on_exit),
            )

        self._icon = pystray.Icon(
            "Z7_SentinelTray",
            _make_green_eye(),
            "Z7_SentinelTray",
            menu,
        )
        self._thread = threading.Thread(
            target=self._icon.run,
            daemon=True,
            name="tray-icon",
        )
        self._thread.start()
        self._close_handler = _install_close_to_tray_handler(self)
        LOGGER.info("Tray icon started", extra={"category": "startup"})

    def stop(self) -> None:
        """Stop the tray icon."""
        if self._close_handler is not None:
            try:
                ctypes.windll.kernel32.SetConsoleCtrlHandler(self._close_handler, False)  # type: ignore[attr-defined]
            except Exception as exc:
                LOGGER.debug("SetConsoleCtrlHandler uninstall failed: %s", exc)
            self._close_handler = None
        if self._icon is not None:
            if self._on_open_status is None:
                # Legacy mode: restore console on exit
                set_console_visible(True)
            try:
                self._icon.stop()
            except Exception as exc:
                LOGGER.debug("Tray icon stop error: %s", exc, extra={"category": "startup"})
            self._icon = None

    def is_running(self) -> bool:
        """Return ``True`` if the tray icon thread is alive."""
        return self._thread is not None and self._thread.is_alive()
