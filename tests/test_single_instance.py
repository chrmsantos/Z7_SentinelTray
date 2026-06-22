from pathlib import Path

import pytest

from z7_sentineltray import entrypoint
from z7_sentineltray.config import get_user_data_dir


def test_terminate_existing_instance_calls_taskkill(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    pid_path = get_user_data_dir() / "z7_sentineltray.pid"
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text("1234", encoding="utf-8")

    called: dict[str, list[str]] = {}

    def fake_run(args, **_kwargs):
        called["args"] = args
        return type("R", (), {"returncode": 0, "stderr": ""})()

    monkeypatch.setattr(entrypoint.subprocess, "run", fake_run)

    assert entrypoint._terminate_existing_instance() is True
    assert called["args"][0] == "taskkill"
    assert called["args"][2] == "1234"


def test_single_instance_acquires_mutex_and_writes_pid(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    pid_path = get_user_data_dir() / "z7_sentineltray.pid"
    pid_path.parent.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(entrypoint, "_ensure_single_instance_mutex", lambda: True)
    monkeypatch.setattr(entrypoint.os, "getpid", lambda: 4321)

    entrypoint._ensure_single_instance()

    assert pid_path.read_text(encoding="utf-8") == "4321"


def test_mutex_returns_false_when_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeKernel32:
        def CreateMutexW(self, *_args):  # noqa: N802
            return 123

        def GetLastError(self) -> int:  # noqa: N802
            return 183

    class FakeWindll:
        kernel32 = FakeKernel32()

    monkeypatch.setattr(entrypoint, "_mutex_handle", None)
    monkeypatch.setattr(entrypoint.ctypes, "windll", FakeWindll())
    assert entrypoint._ensure_single_instance_mutex() is False


def test_mutex_returns_true_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeKernel32:
        def CreateMutexW(self, *_args):  # noqa: N802
            return 123

        def GetLastError(self) -> int:  # noqa: N802
            return 0

    class FakeWindll:
        kernel32 = FakeKernel32()

    monkeypatch.setattr(entrypoint, "_mutex_handle", None)
    monkeypatch.setattr(entrypoint.ctypes, "windll", FakeWindll())
    assert entrypoint._ensure_single_instance_mutex() is True


def test_mutex_falls_back_to_local_when_global_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class FakeKernel32:
        def CreateMutexW(self, *_args):  # noqa: N802
            name = _args[2] if len(_args) > 2 else ""
            calls.append(str(name))
            if "Global" in str(name):
                raise RuntimeError("access denied")
            return 123

        def GetLastError(self) -> int:  # noqa: N802
            return 0

    class FakeWindll:
        kernel32 = FakeKernel32()

    monkeypatch.setattr(entrypoint, "_mutex_handle", None)
    monkeypatch.setattr(entrypoint.ctypes, "windll", FakeWindll())
    assert entrypoint._ensure_single_instance_mutex() is True
    assert any("Global" in name for name in calls)
    assert any("Local" in name for name in calls)
