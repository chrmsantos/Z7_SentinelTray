"""Tests for UI theme persistence across sessions (_ThemeState)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from z7_sentineltray.gui_app import _ThemeState

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _prefs_path(data_dir: Path) -> Path:
    return data_dir / "ui_prefs.json"


# ---------------------------------------------------------------------------
# Default behaviour
# ---------------------------------------------------------------------------


def test_default_theme_is_light(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Without a saved preference file, light mode is the default."""
    monkeypatch.setenv("Z7_SENTINELTRAY_DATA_DIR", str(tmp_path))
    state = _ThemeState()
    assert state.is_dark is False


def test_default_palette_is_light_palette(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("Z7_SENTINELTRAY_DATA_DIR", str(tmp_path))
    state = _ThemeState()
    # Light palette has a white background colour
    assert state.palette["bg"] == "#ffffff"


# ---------------------------------------------------------------------------
# Save / load round-trip
# ---------------------------------------------------------------------------


def test_save_writes_json_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("Z7_SENTINELTRAY_DATA_DIR", str(tmp_path))
    state = _ThemeState()
    state._dark = True
    state._save()

    prefs = _prefs_path(tmp_path)
    assert prefs.exists()
    data = json.loads(prefs.read_text(encoding="utf-8"))
    assert data == {"dark_theme": True}


def test_load_restores_dark_theme_from_save(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A new session should restore the previously saved dark theme."""
    monkeypatch.setenv("Z7_SENTINELTRAY_DATA_DIR", str(tmp_path))

    # First session: user switches to dark
    session1 = _ThemeState()
    assert session1.is_dark is False
    session1._dark = True
    session1._save()

    # Second session: new instance should load from file
    session2 = _ThemeState()
    assert session2.is_dark is True


def test_load_restores_dark_theme(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Dark preference is also preserved across sessions."""
    monkeypatch.setenv("Z7_SENTINELTRAY_DATA_DIR", str(tmp_path))

    _prefs_path(tmp_path).write_text(json.dumps({"dark_theme": True}), encoding="utf-8")

    state = _ThemeState()
    assert state.is_dark is True


def test_light_palette_loaded_after_save(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("Z7_SENTINELTRAY_DATA_DIR", str(tmp_path))

    _prefs_path(tmp_path).write_text(json.dumps({"dark_theme": False}), encoding="utf-8")

    state = _ThemeState()
    assert state.is_dark is False
    # Light palette has a white background
    assert state.palette["bg"] == "#ffffff"


# ---------------------------------------------------------------------------
# Resilience
# ---------------------------------------------------------------------------


def test_corrupted_prefs_falls_back_to_light(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("Z7_SENTINELTRAY_DATA_DIR", str(tmp_path))
    _prefs_path(tmp_path).write_text("not valid json", encoding="utf-8")

    state = _ThemeState()
    assert state.is_dark is False


def test_save_creates_parent_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_save() must create the config directory if it doesn't exist yet."""
    data_dir = tmp_path / "nested" / "config"
    monkeypatch.setenv("Z7_SENTINELTRAY_DATA_DIR", str(data_dir))

    state = _ThemeState()
    state._save()

    assert (data_dir / "ui_prefs.json").exists()
