import sys
from pathlib import Path

import pytest

from z7_sentineltray import entrypoint
from z7_sentineltray.config import get_user_data_dir


def test_ensure_local_override_creates_template_when_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local_path = tmp_path / "config.local.yaml"
    monkeypatch.setattr(entrypoint.subprocess, "Popen", lambda *_a, **_k: None)

    with pytest.raises(SystemExit) as exc_info:
        entrypoint._ensure_local_override(local_path)

    assert local_path.exists(), "template file should have been created"
    content = local_path.read_text(encoding="utf-8")
    assert "monitors:" in content
    assert "smtp_host" in content
    assert "window_title_regex" in content
    assert "template created" in str(exc_info.value).lower()


def test_ensure_local_override_rejects_empty_file(tmp_path: Path) -> None:
    local_path = tmp_path / "config.local.yaml"
    local_path.write_text("\n", encoding="utf-8")

    with pytest.raises(SystemExit):
        entrypoint._ensure_local_override(local_path)


def test_main_requires_local_override_when_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "argv", ["main.py"])
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv(
        "Z7_SENTINELTRAY_ROOT",
        str(tmp_path),
    )
    monkeypatch.setattr(entrypoint, "_setup_boot_logging", lambda: None)
    monkeypatch.setattr(entrypoint, "_ensure_single_instance", lambda: None)
    monkeypatch.setattr(entrypoint, "_ensure_windows", lambda: None)

    def fake_first_run_gui(path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# template\n", encoding="utf-8")
        raise SystemExit("cancelled")

    monkeypatch.setattr(entrypoint, "_first_run_gui_setup", fake_first_run_gui)

    local_path = get_user_data_dir() / "config.local.yaml"
    assert not local_path.exists()

    with pytest.raises(SystemExit):
        entrypoint.main()

    assert local_path.exists(), "template file should have been created"


def test_main_rejects_extra_args(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["main.py", "--other"])
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr(entrypoint, "_setup_boot_logging", lambda: None)
    monkeypatch.setattr(entrypoint, "_ensure_single_instance", lambda: None)

    with pytest.raises(SystemExit):
        entrypoint.main()


def test_ensure_single_instance_already_running(monkeypatch: pytest.MonkeyPatch) -> None:
    notice = {"called": False}

    monkeypatch.setattr(entrypoint, "_ensure_single_instance_mutex", lambda: False)
    monkeypatch.setattr(
        entrypoint,
        "_show_already_running_notice",
        lambda: notice.__setitem__("called", True),
    )

    with pytest.raises(SystemExit) as excinfo:
        entrypoint._ensure_single_instance()

    assert excinfo.value.code == 0
    assert notice["called"] is True
