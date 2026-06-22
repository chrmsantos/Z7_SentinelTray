from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

_REAL_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _isolate_runtime_dirs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Isolate tests from user-specific directories and keep logs/data in temp."""
    data_dir = tmp_path / "config"
    root_dir = tmp_path / "Root"
    data_dir.mkdir(parents=True, exist_ok=True)
    root_dir.mkdir(parents=True, exist_ok=True)

    # Copy the config template so _load_config_template() works under isolation.
    src_example = _REAL_ROOT / "config" / "config.local.yaml.example"
    if src_example.exists():
        dst_config = root_dir / "config"
        dst_config.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_example, dst_config / "config.local.yaml.example")

    monkeypatch.setenv("Z7_SENTINELTRAY_DATA_DIR", str(data_dir))
    monkeypatch.setenv("Z7_SENTINELTRAY_ROOT", str(root_dir))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    if "USERPROFILE" not in os.environ:
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
