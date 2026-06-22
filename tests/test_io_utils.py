from __future__ import annotations

from pathlib import Path

from z7_sentineltray.io_utils import atomic_write_text


def test_atomic_write_text_writes_file(tmp_path: Path) -> None:
    target = tmp_path / "data" / "out.txt"
    atomic_write_text(target, "hello", encoding="utf-8")
    assert target.read_text(encoding="utf-8") == "hello"
