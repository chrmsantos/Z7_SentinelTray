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
from z7_sentineltray.updater import UpdateProgressWindow, _restart_application, parse_version, run_update_check


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

    @patch("z7_sentineltray.updater._restart_application")
    @patch("z7_sentineltray.updater.urllib.request.urlopen")
    @patch("z7_sentineltray.updater.messagebox")
    @patch("z7_sentineltray.updater.tk")
    @patch("z7_sentineltray.updater.ttk")
    @patch("ctypes.windll.kernel32.CloseHandle")
    @patch("subprocess.Popen")
    @patch("z7_sentineltray.updater.threading.Thread", SynchronousThread)
    def test_update_download_success_frozen_mode(
        self, mock_popen, mock_close_handle, mock_ttk, mock_tk, mock_msgbox, mock_urlopen, mock_restart
    ) -> None:
        """Test complete update installation flow in frozen (production) mode."""
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

                # Verify process NOT restarted via subprocess.Popen directly
                mock_popen.assert_not_called()

                # Verify Tkinter parent quit NOT called
                parent.quit.assert_not_called()

                # Verify showinfo called with new success message mentioning restart
                mock_msgbox.showinfo.assert_called_once_with(
                    "Atualização Concluída",
                    "A atualização foi baixada e instalada com sucesso!\n\n"
                    "O aplicativo será reiniciado automaticamente na nova versão.\n"
                    "Caso isso não ocorra, feche e reabra o aplicativo manualmente.",
                    parent=parent,
                )

                # Verify _restart_application was called with the exe path
                mock_restart.assert_called_once_with(temp_exe)

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


class TestRestartApplication(unittest.TestCase):
    """Test suite for the _restart_application function and its strategies."""

    class _ExitCalled(SystemExit):
        """Sentinel exception raised when os._exit is called in tests."""

    def _make_exit_side_effect(self):
        """Create a side effect for os._exit that raises _ExitCalled."""
        def side_effect(code=0):
            raise self._ExitCalled(code)
        return side_effect

    @patch("z7_sentineltray.updater.subprocess.Popen")
    def test_strategy1_popen_succeeds(self, mock_popen) -> None:
        """Test that Strategy 1 (subprocess.Popen) launches and exits."""
        from z7_sentineltray.updater import _restart_application

        with tempfile.TemporaryDirectory() as tmp_dir:
            exe_path = Path(tmp_dir) / "Z7_SentinelTray.exe"
            exe_path.write_text("fake_exe", encoding="utf-8")

            with patch("z7_sentineltray.updater.os._exit", side_effect=self._make_exit_side_effect()):
                with self.assertRaises(self._ExitCalled):
                    _restart_application(exe_path)

            mock_popen.assert_called_once()
            call_args = mock_popen.call_args
            assert str(exe_path) in call_args[0][0]

    @patch("z7_sentineltray.updater.subprocess.Popen")
    def test_strategy1_popen_fails_falls_to_strategy2(
        self, mock_popen
    ) -> None:
        """Test that when Popen fails, Strategy 2 (batch script) is tried."""
        from z7_sentineltray.updater import _restart_application

        mock_popen.side_effect = [PermissionError("Access denied"), MagicMock()]

        with tempfile.TemporaryDirectory() as tmp_dir:
            exe_path = Path(tmp_dir) / "Z7_SentinelTray.exe"
            exe_path.write_text("fake_exe", encoding="utf-8")

            with patch("z7_sentineltray.updater.os._exit", side_effect=self._make_exit_side_effect()):
                with self.assertRaises(self._ExitCalled):
                    _restart_application(exe_path)

            assert mock_popen.call_count == 2
            second_call_args = mock_popen.call_args_list[1]
            assert "cmd.exe" in second_call_args[0][0]

    @patch("z7_sentineltray.updater.os.startfile")
    @patch("z7_sentineltray.updater.subprocess.Popen")
    def test_strategy1_and_2_fail_falls_to_strategy3_vbs(
        self, mock_popen, mock_startfile
    ) -> None:
        """Test that when Popen and batch script fail, VBScript (strategy 3) is tried."""
        from z7_sentineltray.updater import _restart_application

        # Strategy 1 fails, Strategy 2 fails, Strategy 3 (VBScript) succeeds
        mock_popen.side_effect = [
            PermissionError("Access denied"),
            PermissionError("Access denied"),
            MagicMock(),
        ]

        with tempfile.TemporaryDirectory() as tmp_dir:
            exe_path = Path(tmp_dir) / "Z7_SentinelTray.exe"
            exe_path.write_text("fake_exe", encoding="utf-8")

            with patch("z7_sentineltray.updater.os._exit", side_effect=self._make_exit_side_effect()):
                with self.assertRaises(self._ExitCalled):
                    _restart_application(exe_path)

            assert mock_popen.call_count == 3
            third_call = mock_popen.call_args_list[2]
            _args, kwargs = third_call
            assert "wscript.exe" in _args[0][0]
            # The .vbs script file should exist and contain the PID
            vbs_path = Path(_args[0][1])
            assert vbs_path.exists()
            vbs_content = vbs_path.read_text(encoding="utf-8")
            assert f"targetPID = {os.getpid()}" in vbs_content
            assert str(exe_path.resolve()).replace("\\", "\\\\") in vbs_content

    @patch("z7_sentineltray.updater.os.startfile")
    @patch("z7_sentineltray.updater.subprocess.Popen")
    def test_all_strategies_fail_logs_error(
        self, mock_popen, mock_startfile
    ) -> None:
        """Test that when all 5 strategies fail, error is logged and no exit."""
        from z7_sentineltray.updater import _restart_application

        mock_popen.side_effect = PermissionError("Access denied")
        mock_startfile.side_effect = OSError("ShellExecute failed")

        with tempfile.TemporaryDirectory() as tmp_dir:
            exe_path = Path(tmp_dir) / "Z7_SentinelTray.exe"
            exe_path.write_text("fake_exe", encoding="utf-8")

            _restart_application(exe_path)

            # 4 Popen calls: strategy 1 (direct), 2 (batch), 3 (vbs), 4 (powershell)
            assert mock_popen.call_count == 4
            mock_startfile.assert_called_once()

    def test_nonexistent_exe_logs_error(self) -> None:
        """Test that non-existent exe path logs error and returns."""
        from z7_sentineltray.updater import _restart_application

        fake_path = Path("/nonexistent/path/Z7_SentinelTray.exe")

        with patch("z7_sentineltray.updater.subprocess.Popen") as mock_popen, \
             patch("z7_sentineltray.updater.os.startfile") as mock_startfile:
            _restart_application(fake_path)

            mock_popen.assert_not_called()
            mock_startfile.assert_not_called()

    @patch("z7_sentineltray.updater.subprocess.Popen")
    def test_strategy1_uses_detached_process_flags(self, mock_popen) -> None:
        """Test that Strategy 1 uses DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP."""
        from z7_sentineltray.updater import _restart_application

        with tempfile.TemporaryDirectory() as tmp_dir:
            exe_path = Path(tmp_dir) / "Z7_SentinelTray.exe"
            exe_path.write_text("fake_exe", encoding="utf-8")

            with patch("z7_sentineltray.updater.os._exit", side_effect=self._make_exit_side_effect()):
                with self.assertRaises(self._ExitCalled):
                    _restart_application(exe_path)

            call_kwargs = mock_popen.call_args[1]
            expected_flags = 0x00000008 | 0x00000200
            assert call_kwargs["creationflags"] == expected_flags
            assert call_kwargs["close_fds"] is True

    @patch("z7_sentineltray.updater.subprocess.Popen")
    def test_strategy2_creates_batch_script(self, mock_popen) -> None:
        """Test that Strategy 2 creates a .cmd batch script in temp dir."""
        from z7_sentineltray.updater import _restart_application

        mock_popen.side_effect = [PermissionError("denied"), MagicMock()]

        with tempfile.TemporaryDirectory() as tmp_dir:
            exe_path = Path(tmp_dir) / "Z7_SentinelTray.exe"
            exe_path.write_text("fake_exe", encoding="utf-8")

            with patch("z7_sentineltray.updater.os._exit", side_effect=self._make_exit_side_effect()):
                with self.assertRaises(self._ExitCalled):
                    _restart_application(exe_path)

            second_call = mock_popen.call_args_list[1]
            args = second_call[0][0]
            assert args[0] == "cmd.exe"
            assert args[1] == "/c"
            bat_path = Path(args[2])
            assert bat_path.suffix == ".cmd"
            assert bat_path.name.startswith("z7_restart_")

    @patch("z7_sentineltray.updater.subprocess.Popen")
    def test_strategy2_batch_script_contains_pid(self, mock_popen) -> None:
        """Test that the batch script contains the current PID for wait logic."""
        from z7_sentineltray.updater import _restart_application

        mock_popen.side_effect = [PermissionError("denied"), MagicMock()]

        with tempfile.TemporaryDirectory() as tmp_dir:
            exe_path = Path(tmp_dir) / "Z7_SentinelTray.exe"
            exe_path.write_text("fake_exe", encoding="utf-8")

            with patch("z7_sentineltray.updater.os._exit", side_effect=self._make_exit_side_effect()):
                with self.assertRaises(self._ExitCalled):
                    _restart_application(exe_path)

            second_call = mock_popen.call_args_list[1]
            bat_path = Path(second_call[0][0][2])
            bat_content = bat_path.read_text(encoding="utf-8")
            assert f"set TARGET_PID={os.getpid()}" in bat_content
            assert "tasklist" in bat_content
            assert "WAIT_LOOP" in bat_content
            assert str(exe_path) in bat_content

    @patch("z7_sentineltray.updater.subprocess.Popen")
    def test_restart_resolves_path(self, mock_popen) -> None:
        """Test that _restart_application resolves the exe path."""
        from z7_sentineltray.updater import _restart_application

        with tempfile.TemporaryDirectory() as tmp_dir:
            subdir = Path(tmp_dir) / "sub"
            subdir.mkdir()
            exe_path = subdir / ".." / "Z7_SentinelTray.exe"
            exe_path.resolve().write_text("fake_exe", encoding="utf-8")

            with patch("z7_sentineltray.updater.os._exit", side_effect=self._make_exit_side_effect()):
                with self.assertRaises(self._ExitCalled):
                    _restart_application(exe_path)

            call_args = mock_popen.call_args
            launched_path = Path(call_args[0][0][0])
            assert ".." not in str(launched_path)

    @patch("z7_sentineltray.updater.subprocess.Popen")
    def test_strategy3_vbs_creates_temp_script_with_prefix(
        self, mock_popen
    ) -> None:
        """Test strategy 3: VBScript file created with correct prefix and extension."""
        from z7_sentineltray.updater import _restart_application

        mock_popen.side_effect = [
            PermissionError("denied"),
            PermissionError("denied"),
            MagicMock(),
        ]

        with tempfile.TemporaryDirectory() as tmp_dir:
            exe_path = Path(tmp_dir) / "Z7_SentinelTray.exe"
            exe_path.write_text("fake_exe", encoding="utf-8")

            with patch("z7_sentineltray.updater.os._exit", side_effect=self._make_exit_side_effect()):
                with self.assertRaises(self._ExitCalled):
                    _restart_application(exe_path)

            third_call_cmd = mock_popen.call_args_list[2][0][0]
            assert third_call_cmd[0] == "wscript.exe"
            vbs_path = Path(third_call_cmd[1])
            assert vbs_path.suffix == ".vbs"
            assert vbs_path.name.startswith("z7_restart_")

    @patch("z7_sentineltray.updater.subprocess.Popen")
    def test_strategy4_powershell_passes_args(self, mock_popen) -> None:
        """Test strategy 4: PowerShell cmd args contain required flags."""
        from z7_sentineltray.updater import _restart_application

        mock_popen.side_effect = [
            PermissionError("denied"),
            PermissionError("denied"),
            PermissionError("denied"),
            MagicMock(),
        ]

        with tempfile.TemporaryDirectory() as tmp_dir:
            exe_path = Path(tmp_dir) / "Z7_SentinelTray.exe"
            exe_path.write_text("fake_exe", encoding="utf-8")

            with patch("z7_sentineltray.updater.os._exit", side_effect=self._make_exit_side_effect()):
                with self.assertRaises(self._ExitCalled):
                    _restart_application(exe_path)

            cmd = mock_popen.call_args_list[3][0][0]
            assert cmd[0] == "powershell.exe"
            assert "-ExecutionPolicy" in cmd
            assert cmd[cmd.index("-ExecutionPolicy") + 1] == "Bypass"
            assert "-WindowStyle" in cmd
            assert cmd[cmd.index("-WindowStyle") + 1] == "Hidden"
            ps_command = cmd[cmd.index("-Command") + 1]
            assert "Start-Process" in ps_command

    @patch("z7_sentineltray.updater.subprocess.Popen")
    def test_strategy4_uses_detached_flags(self, mock_popen) -> None:
        """Test strategy 4: PowerShell uses DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP."""
        from z7_sentineltray.updater import _restart_application

        mock_popen.side_effect = [
            PermissionError("denied"),
            PermissionError("denied"),
            PermissionError("denied"),
            MagicMock(),
        ]

        with tempfile.TemporaryDirectory() as tmp_dir:
            exe_path = Path(tmp_dir) / "Z7_SentinelTray.exe"
            exe_path.write_text("fake_exe", encoding="utf-8")

            with patch("z7_sentineltray.updater.os._exit", side_effect=self._make_exit_side_effect()):
                with self.assertRaises(self._ExitCalled):
                    _restart_application(exe_path)

            call_kwargs = mock_popen.call_args_list[3][1]
            expected_flags = 0x00000008 | 0x00000200
            assert call_kwargs["creationflags"] == expected_flags
            assert call_kwargs["close_fds"] is True

    @patch("z7_sentineltray.updater._restart_application")
    @patch("z7_sentineltray.updater.urllib.request.urlopen")
    @patch("z7_sentineltray.updater.messagebox")
    @patch("z7_sentineltray.updater.tk")
    @patch("z7_sentineltray.updater.ttk")
    @patch("z7_sentineltray.updater.threading.Thread", SynchronousThread)
    def test_successful_update_shows_restart_message_and_calls_restart(
        self, mock_ttk, mock_tk, mock_msgbox, mock_urlopen, mock_restart
    ) -> None:
        """Test that successful update shows restart message and calls _restart_application."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            temp_exe = tmp_path / "Z7_SentinelTray.exe"
            temp_exe.write_text("original_content", encoding="utf-8")

            mock_urlopen.return_value = MockResponse(
                b"updated_frozen_exe_payload", {"Content-Length": "26"}
            )

            parent = MagicMock()
            theme = DummyTheme()
            mock_tk.Toplevel.return_value.after.side_effect = lambda delay, func: func()

            with patch("sys.frozen", True, create=True), \
                 patch("z7_sentineltray.updater.sys.executable", str(temp_exe)):

                window = UpdateProgressWindow(
                    parent, theme, "http://example.com/download", temp_exe
                )

                # Verify the success message mentions restart
                mock_msgbox.showinfo.assert_called_once()
                call_args = mock_msgbox.showinfo.call_args
                msg_text = call_args[0][1]
                assert "reiniciado automaticamente" in msg_text

                # Verify _restart_application was called with the exe path
                mock_restart.assert_called_once_with(temp_exe)
