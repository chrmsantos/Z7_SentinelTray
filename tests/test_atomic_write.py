from pathlib import Path

from z7_sentineltray.telemetry import atomic_write_text


def test_atomic_write_text_replaces_and_cleans_temp(tmp_path: Path) -> None:
    path = tmp_path / "status.json"

    atomic_write_text(path, "first", encoding="utf-8")
    atomic_write_text(path, "second", encoding="utf-8")

    assert path.read_text(encoding="utf-8") == "second"
    assert list(tmp_path.glob("*.tmp")) == []
