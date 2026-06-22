from __future__ import annotations

from pathlib import Path


def test_build_named_exe_script_exists_and_mentions_pyinstaller() -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "build_named_exe.ps1"
    content = script.read_text(encoding="utf-8")
    assert "PyInstaller" in content
    assert "Z7_SentinelTray.exe" in content
    assert "build_exe_" in content
