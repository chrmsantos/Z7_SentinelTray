"""Tests for the updater module."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from z7_sentineltray.status import StatusStore
from z7_sentineltray.updater import UpdateProgressWindow, parse_version, run_update_check


class TestUpdater(unittest.TestCase):
    """Test case for update system functions."""

    def test_parse_version_standard(self) -> None:
        """Test parsing standard version strings."""
        assert parse_version("6.1.5") == (6, 1, 5)
        assert parse_version("1.0.0") == (1, 0, 0)

    def test_parse_version_v_prefix(self) -> None:
        """Test parsing version strings with 'v' or 'V' prefix."""
        assert parse_version("v6.2.0") == (6, 2, 0)
        assert parse_version("V12.3.4") == (12, 3, 4)

    def test_parse_version_with_metadata(self) -> None:
        """Test parsing version strings with alpha/beta/metadata suffixes."""
        assert parse_version("6.2.0-beta.1") == (6, 2, 0, 1)
        assert parse_version("v6.2.0-rc2") == (6, 2, 0, 2)

    def test_version_comparison(self) -> None:
        """Test direct tuple comparison of parsed versions."""
        assert parse_version("6.2.0") > parse_version("6.1.5")
        assert parse_version("v6.2.0") > parse_version("v6.1.5")
        assert parse_version("v10.0.0") > parse_version("v9.9.9")
        assert parse_version("6.1.5") == parse_version("v6.1.5")


class SynchronousThread:
    """A mock Thread class that runs its target synchronously upon start()."""

    def __init__(self, group=None, target=None, name=None, args=(), kwargs=None, *, daemon=None):
        self.target = target
        self.args = args
        self.kwargs = kwargs or {}

    def start(self):
        if self.target:
            self.target(*self.args, **self.kwargs)


class NoAutoStartThread:
    """A mock Thread that records its target but does NOT call it on start().

    Use when the test must drive ``_run_download()`` manually after construction.
    """

    def __init__(self, group=None, target=None, name=None, args=(), kwargs=None, *, daemon=None):
        self.target = target
        self.args = args
        self.kwargs = kwargs or {}

    def start(self) -> None:
        """No-op: intentionally does not run the target."""


class DummyTheme:
    """Dummy theme object to supply a palette dictionary to UpdateProgressWindow."""

    def __init__(self):
        self.palette = {
            "bg": "#1e1e1e",
            "surface": "#252526",
            "border": "#3c3c3c",
            "green": "#4ec9b0",
            "text": "#cccccc",
            "white": "#ffffff",
        }


class MockResponse:
    """Mock HTTP response object implementing read, info, and context manager protocols."""

    def __init__(self, data: bytes, headers: dict[str, str] | None = None):
        self.data = data
        self.headers = headers or {}

    def read(self, block_size: int | None = None) -> bytes:
        if block_size is None or len(self.data) <= block_size:
            chunk = self.data
            self.data = b""
            return chunk
        chunk = self.data[:block_size]
        self.data = self.data[block_size:]
        return chunk

    def info(self):
        class Info:
            def __init__(self, headers):
                self.headers = headers
            def get(self, key, default=None):
                return self.headers.get(key, default)
        return Info(self.headers)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


class TestUpdateProcess(unittest.TestCase):
    """Test suite covering all paths of the update check and installation flow."""

    @patch("z7_sentineltray.updater.urllib.request.urlopen")
    @patch("z7_sentineltray.updater.messagebox")
    @patch("z7_sentineltray.updater.threading.Thread", SynchronousThread)
    def test_update_check_up_to_date(self, mock_msgbox, mock_urlopen) -> None:
        """Test update check when current version is up-to-date or newer."""
        # Mock release response returning version 6.1.5 (same as current)
        release_data = {
            "tag_name": "v6.1.5",
            "prerelease": False,
            "draft": False,
            "assets": [
                {"name": "Z7_SentinelTray.exe", "browser_download_url": "http://example.com/download"}
            ]
        }
        # Use side_effect list so each urlopen() call gets a fresh MockResponse (data not consumed).
        payload = json.dumps(release_data).encode("utf-8")
        mock_urlopen.side_effect = [
            MockResponse(payload),
            MockResponse(payload),
        ]

        status = StatusStore()
        parent = MagicMock()
        # Execute parent.after(delay, func) callbacks synchronously so messagebox calls fire.
        parent.after.side_effect = lambda delay, func: func()
        theme = DummyTheme()

        # Startup check: should be silent (no messagebox)
        run_update_check(parent, theme, "6.1.5", on_startup=True, status=status)
        assert status.snapshot().update_status == "Atualizado"
        mock_msgbox.showinfo.assert_not_called()

        # Manual check: should show info dialog
        run_update_check(parent, theme, "6.1.5", on_startup=False, status=status)
        mock_msgbox.showinfo.assert_called_once_with(
            "Atualização",
            "Você já está na versão estável mais recente do aplicativo.",
            parent=parent,
        )

    @patch("z7_sentineltray.updater.urllib.request.urlopen")
    @patch("z7_sentineltray.updater.messagebox")
    @patch("z7_sentineltray.updater.threading.Thread", SynchronousThread)
    def test_update_check_no_compatible_asset(self, mock_msgbox, mock_urlopen) -> None:
        """Test update check when newer version exists but has no compatible executable."""
        release_data = {
            "tag_name": "v6.2.0",
            "prerelease": False,
            "draft": False,
            "assets": [
                {"name": "source.tar.gz", "browser_download_url": "http://example.com/source"}
            ]
        }
        mock_urlopen.return_value = MockResponse(json.dumps(release_data).encode("utf-8"))

        status = StatusStore()
        parent = MagicMock()
        # Execute parent.after(delay, func) callbacks synchronously so messagebox calls fire.
        parent.after.side_effect = lambda delay, func: func()
        theme = DummyTheme()

        run_update_check(parent, theme, "6.1.5", on_startup=False, status=status)

        assert status.snapshot().update_status == "Atualização disponível (v6.2.0)"
        mock_msgbox.showwarning.assert_called_once_with(
            "Atualização",
            "A versão v6.2.0 está disponível, mas nenhum executável compatível foi encontrado no GitHub.",
            parent=parent,
        )

    @patch("z7_sentineltray.updater.urllib.request.urlopen")
    @patch("z7_sentineltray.updater.messagebox")
    @patch("z7_sentineltray.updater.threading.Thread", SynchronousThread)
    def test_update_check_user_declines(self, mock_msgbox, mock_urlopen) -> None:
        """Test update check when update is available but user declines the download."""
        release_data = {
            "tag_name": "v6.2.0",
            "prerelease": False,
            "draft": False,
            "assets": [
                {"name": "Z7_SentinelTray.exe", "browser_download_url": "http://example.com/download"}
            ]
        }
        mock_urlopen.return_value = MockResponse(json.dumps(release_data).encode("utf-8"))
        mock_msgbox.askyesno.return_value = False  # User clicks No

        status = StatusStore()
        parent = MagicMock()
        # Execute parent.after(delay, func) callbacks synchronously so messagebox calls fire.
        parent.after.side_effect = lambda delay, func: func()
        theme = DummyTheme()

        run_update_check(parent, theme, "6.1.5", on_startup=False, status=status)

        assert status.snapshot().update_status == "Atualização disponível (v6.2.0)"
        mock_msgbox.askyesno.assert_called_once()

    @patch("z7_sentineltray.updater.urllib.request.urlopen")
    @patch("z7_sentineltray.updater.messagebox")
    @patch("z7_sentineltray.updater.threading.Thread", SynchronousThread)
    def test_update_check_available_on_startup(self, mock_msgbox, mock_urlopen) -> None:
        """Test update check when update is available and on_startup is True (no prompt)."""
        release_data = {
            "tag_name": "v6.2.0",
            "prerelease": False,
            "draft": False,
            "assets": [
                {"name": "Z7_SentinelTray.exe", "browser_download_url": "http://example.com/download"}
            ]
        }
        mock_urlopen.return_value = MockResponse(json.dumps(release_data).encode("utf-8"))

        status = StatusStore()
        parent = MagicMock()
        parent.after.side_effect = lambda delay, func: func()
        theme = DummyTheme()

        run_update_check(parent, theme, "6.1.5", on_startup=True, status=status)

        assert status.snapshot().update_status == "Atualização disponível (v6.2.0)"
        mock_msgbox.askyesno.assert_not_called()

    @patch("z7_sentineltray.updater.urllib.request.urlopen")
    @patch("z7_sentineltray.updater.messagebox")
    @patch("z7_sentineltray.updater.tk")
    @patch("z7_sentineltray.updater.ttk")
    @patch("z7_sentineltray.updater.threading.Thread", SynchronousThread)
    def test_update_check_user_accepts(self, mock_ttk, mock_tk, mock_msgbox, mock_urlopen) -> None:
        """Test update check and successful download simulation in development mode."""
        release_data = {
            "tag_name": "v6.2.0",
            "prerelease": False,
            "draft": False,
            "assets": [
                {"name": "Z7_SentinelTray.exe", "browser_download_url": "http://example.com/download"}
            ]
        }
        mock_urlopen.side_effect = [
            MockResponse(json.dumps(release_data).encode("utf-8")),
            MockResponse(b"mock_binary_exe_payload", {"Content-Length": "23"}),
        ]
        mock_msgbox.askyesno.return_value = True  # User clicks Yes
        # Execute win.after(delay, func) callbacks synchronously so _finalize_update fires.
        mock_tk.Toplevel.return_value.after.side_effect = lambda delay, func: func()

        with patch("sys.frozen", False, create=True), \
             patch("z7_sentineltray.config.get_project_root") as mock_root:

            with tempfile.TemporaryDirectory() as tmp_dir:
                tmp_path = Path(tmp_dir)
                mock_root.return_value = tmp_path
                # Point sys.executable into tmp_dir so the .tmp_download file is created there.
                fake_exe = tmp_path / "Z7_SentinelTray.exe"
                dev_exe = tmp_path / "dist" / "Z7_SentinelTray.exe"

                with patch("z7_sentineltray.updater.sys.executable", str(fake_exe)):
                    status = StatusStore()
                    parent = MagicMock()
                    # Execute parent.after(delay, func) callbacks synchronously so messagebox calls fire.
                    parent.after.side_effect = lambda delay, func: func()
                    theme = DummyTheme()

                    run_update_check(parent, theme, "6.1.5", on_startup=False, status=status)

                assert status.snapshot().update_status == "Atualização disponível (v6.2.0)"
                mock_msgbox.askyesno.assert_called_once()
                mock_msgbox.showinfo.assert_called_once()

                assert dev_exe.exists()
                assert dev_exe.read_bytes() == b"mock_binary_exe_payload"

    @patch("z7_sentineltray.updater.urllib.request.urlopen")
    @patch("z7_sentineltray.updater.messagebox")
    @patch("z7_sentineltray.updater.tk")
    @patch("z7_sentineltray.updater.ttk")
    @patch("ctypes.windll.kernel32.CloseHandle")
    @patch("subprocess.Popen")
    @patch("z7_sentineltray.updater.threading.Thread", SynchronousThread)
    def test_update_download_success_frozen_mode(
        self, mock_popen, mock_close_handle, mock_ttk, mock_tk, mock_msgbox, mock_urlopen
    ) -> None:
        """Test complete update installation flow (without auto-restart) in frozen (production) mode."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            temp_exe = tmp_path / "Z7_SentinelTray.exe"
            temp_exe.write_text("original_content", encoding="utf-8")

            mock_urlopen.return_value = MockResponse(b"updated_frozen_exe_payload", {"Content-Length": "26"})

            parent = MagicMock()
            theme = DummyTheme()
            # Execute win.after(delay, func) callbacks synchronously so _finalize_update fires.
            mock_tk.Toplevel.return_value.after.side_effect = lambda delay, func: func()

            from z7_sentineltray import entrypoint
            entrypoint._mutex_handle = 12345
            pid_file = tmp_path / "z7_sentineltray.pid"
            pid_file.write_text("9999", encoding="utf-8")

            with patch("sys.frozen", True, create=True), \
                 patch("z7_sentineltray.updater.sys.executable", str(temp_exe)), \
                 patch("z7_sentineltray.entrypoint._pid_file_path", return_value=pid_file), \
                 patch.dict(os.environ, {"_MEIPASS": "old_mei_dir", "OTHER_VAR": "keep_this"}):

                UpdateProgressWindow(parent, theme, "http://example.com/download", temp_exe)

                # Verify file system changes
                assert temp_exe.exists()
                assert temp_exe.read_text(encoding="utf-8") == "updated_frozen_exe_payload"

                old_exe = temp_exe.with_suffix(".exe.old")
                assert old_exe.exists()
                assert old_exe.read_text(encoding="utf-8") == "original_content"

                # Verify PID file still exists (not unlinked)
                assert pid_file.exists()

                # Verify Mutex NOT closed
                mock_close_handle.assert_not_called()
                assert entrypoint._mutex_handle == 12345

                # Verify process NOT restarted
                mock_popen.assert_not_called()

                # Verify Tkinter parent quit NOT called
                parent.quit.assert_not_called()

                # Verify showinfo called with new success message
                mock_msgbox.showinfo.assert_called_once_with(
                    "Atualização Concluída",
                    "A atualização foi baixada e instalada com sucesso!\n\n"
                    "A nova versão estará ativa na próxima inicialização do aplicativo.",
                    parent=parent,
                )

    @patch("z7_sentineltray.updater.urllib.request.urlopen")
    @patch("z7_sentineltray.updater.messagebox")
    @patch("z7_sentineltray.updater.tk")
    @patch("z7_sentineltray.updater.ttk")
    @patch("z7_sentineltray.updater.threading.Thread", NoAutoStartThread)
    def test_update_download_cancellation(self, mock_ttk, mock_tk, mock_msgbox, mock_urlopen) -> None:
        """Test mid-download cancellation requested by the user."""
        mock_msgbox.askyesno.return_value = True

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            temp_exe = tmp_path / "Z7_SentinelTray.exe"

            window_ref = [None]

            def custom_read(block_size):
                # Trigger cancellation on the first read block
                if window_ref[0]:
                    window_ref[0].cancel_event.set()
                return b"some_bytes"

            mock_response = MockResponse(b"", {"Content-Length": "100000"})
            mock_response.read = custom_read
            mock_urlopen.return_value = mock_response

            window = UpdateProgressWindow(
                parent=MagicMock(),
                theme_state=DummyTheme(),
                download_url="http://example.com/download",
                dest_path=temp_exe,
            )
            window_ref[0] = window
            window._run_download()

            temp_dest = temp_exe.with_suffix(".tmp_download")
            assert not temp_dest.exists()

    @patch("z7_sentineltray.updater.urllib.request.urlopen")
    @patch("z7_sentineltray.updater.messagebox")
    @patch("z7_sentineltray.updater.tk")
    @patch("z7_sentineltray.updater.ttk")
    @patch("z7_sentineltray.updater.threading.Thread", SynchronousThread)
    def test_update_download_network_error(self, mock_ttk, mock_tk, mock_msgbox, mock_urlopen) -> None:
        """Test update download error handling when network connection times out."""
        mock_urlopen.side_effect = TimeoutError("Connection timed out")

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            temp_exe = tmp_path / "Z7_SentinelTray.exe"
            # Execute win.after(delay, func) callbacks synchronously so _handle_error fires.
            mock_tk.Toplevel.return_value.after.side_effect = lambda delay, func: func()

            window = UpdateProgressWindow(
                parent=MagicMock(),
                theme_state=DummyTheme(),
                download_url="http://example.com/download",
                dest_path=temp_exe,
            )

            mock_msgbox.showerror.assert_called_once()
            temp_dest = temp_exe.with_suffix(".tmp_download")
            assert not temp_dest.exists()
            window.win.destroy.assert_called_once()

    @patch("z7_sentineltray.updater.urllib.request.urlopen")
    @patch("z7_sentineltray.updater.messagebox")
    @patch("z7_sentineltray.updater.threading.Thread", SynchronousThread)
    def test_update_check_api_error(self, mock_msgbox, mock_urlopen) -> None:
        """Test update check error handling when GitHub API request fails."""
        mock_urlopen.side_effect = Exception("API rate limit exceeded")

        status = StatusStore()
        parent = MagicMock()
        # Execute parent.after(delay, func) callbacks synchronously so messagebox calls fire.
        parent.after.side_effect = lambda delay, func: func()
        theme = DummyTheme()

        # Startup check: silent status update
        run_update_check(parent, theme, "6.1.5", on_startup=True, status=status)
        assert status.snapshot().update_status == "Erro ao verificar"
        mock_msgbox.showerror.assert_not_called()

        # Manual check: displays error popup
        run_update_check(parent, theme, "6.1.5", on_startup=False, status=status)
        mock_msgbox.showerror.assert_called_once()

    def test_check_write_permission(self) -> None:
        """Test check_write_permission helper under writable and read-only directory scenarios."""
        from z7_sentineltray.updater import check_write_permission

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            temp_file = tmp_path / "test.exe"

            # Should return True in a writable directory
            assert check_write_permission(temp_file)

        # Test permission denied by mocking permission error
        with patch("pathlib.Path.touch", side_effect=PermissionError("Permission denied")):
            assert not check_write_permission(Path("dummy_path.exe"))

    @patch("z7_sentineltray.updater.urllib.request.urlopen")
    @patch("z7_sentineltray.updater.messagebox")
    @patch("z7_sentineltray.updater.check_write_permission")
    @patch("z7_sentineltray.updater.threading.Thread", SynchronousThread)
    def test_update_check_write_permission_denied(self, mock_check_write, mock_msgbox, mock_urlopen) -> None:
        """Test that update check handles write permission denial without prompting to download."""
        release_data = {
            "tag_name": "v6.2.0",
            "prerelease": False,
            "draft": False,
            "assets": [
                {"name": "Z7_SentinelTray.exe", "browser_download_url": "http://example.com/download"}
            ]
        }
        mock_urlopen.return_value = MockResponse(json.dumps(release_data).encode("utf-8"))
        mock_check_write.return_value = False  # Simulate write permission denied

        status = StatusStore()
        parent = MagicMock()
        parent.after.side_effect = lambda delay, func: func()
        theme = DummyTheme()

        run_update_check(parent, theme, "6.1.5", on_startup=False, status=status)

        assert status.snapshot().update_status == "Sem permissão de gravação (v6.2.0)"
        mock_msgbox.showwarning.assert_called_once_with(
            "Permissão Negada",
            unittest.mock.ANY,
            parent=parent,
        )
        mock_msgbox.askyesno.assert_not_called()

    @patch("z7_sentineltray.updater.urllib.request.urlopen")
    @patch("z7_sentineltray.updater.messagebox")
    @patch("z7_sentineltray.updater.tk")
    @patch("z7_sentineltray.updater.ttk")
    @patch("z7_sentineltray.updater.os.rename")
    @patch("z7_sentineltray.updater.threading.Thread", SynchronousThread)
    def test_update_download_rename_fails_and_restores(
        self, mock_rename, mock_ttk, mock_tk, mock_msgbox, mock_urlopen
    ) -> None:
        """Test that if renaming the new executable fails, the backup is restored."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            temp_exe = tmp_path / "Z7_SentinelTray.exe"
            temp_exe.write_text("original_content", encoding="utf-8")

            mock_urlopen.return_value = MockResponse(b"updated_frozen_exe_payload", {"Content-Length": "26"})

            parent = MagicMock()
            theme = DummyTheme()
            mock_tk.Toplevel.return_value.after.side_effect = lambda delay, func: func()

            # Mock rename side effect:
            # 1. First rename (backup current to old) succeeds.
            # 2. Second rename (temp to current) fails with PermissionError.
            # 3. Third rename (restore old to current) succeeds.
            calls = []
            def side_effect(src, dst):
                calls.append((src, dst))
                if len(calls) == 2:
                    raise PermissionError("Access denied")
                return None

            mock_rename.side_effect = side_effect

            with patch("sys.frozen", True, create=True), \
                 patch("z7_sentineltray.updater.sys.executable", str(temp_exe)):

                window = UpdateProgressWindow(parent, theme, "http://example.com/download", temp_exe)

                # Verify that rename failed, but backup restore was triggered
                # First call: rename current_exe -> old_exe
                # Second call: rename temp_dest -> current_exe (which fails)
                # Third call: rename old_exe -> current_exe (restore)
                assert len(calls) == 3
                assert Path(calls[0][0]) == Path(temp_exe)
                assert Path(calls[0][1]) == Path(temp_exe).with_suffix(".exe.old")
                assert Path(calls[1][1]) == Path(temp_exe)
                assert Path(calls[2][0]) == Path(temp_exe).with_suffix(".exe.old")
                assert Path(calls[2][1]) == Path(temp_exe)

                mock_msgbox.showerror.assert_called_with(
                    "Erro na Instalação",
                    unittest.mock.ANY,
                    parent=parent,
                )
                window.win.destroy.assert_called_once()
