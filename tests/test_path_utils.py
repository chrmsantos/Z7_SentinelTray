from __future__ import annotations

from pathlib import Path

import pytest

from z7_sentineltray.path_utils import ensure_under_root, resolve_log_path, resolve_sensitive_path


def test_resolve_sensitive_path_under_base(tmp_path: Path) -> None:
    base = tmp_path / "base"
    base.mkdir()
    path = resolve_sensitive_path(base, "state.json")
    assert path == str(base / "state.json")


def test_resolve_log_path_forces_into_log_root(tmp_path: Path) -> None:
    base = tmp_path / "base"
    log_root = tmp_path / "logs"
    base.mkdir()
    log_root.mkdir()

    path = resolve_log_path(base, log_root, str(tmp_path / "other" / "x.log"))
    assert path == str(log_root / "x.log")


def test_ensure_under_root_rejects_outside(tmp_path: Path) -> None:
    log_root = tmp_path / "logs"
    log_root.mkdir()
    outside = tmp_path / "outside.log"

    with pytest.raises(ValueError, match="log_file"):
        ensure_under_root(log_root, str(outside), "log_file")
