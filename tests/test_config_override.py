from pathlib import Path

import pytest

from z7_sentineltray.config import load_config_with_override


def test_load_config_with_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    base_path = Path(__file__).parent / "data" / "config.yaml"
    override_path = Path(__file__).parent / "data" / "config_override.yaml"

    config = load_config_with_override(str(base_path), str(override_path))

    assert config.monitors[0].window_title_regex == "SECRET_APP"
    assert config.monitors[0].email.to_addresses == ["local@example.com"]
    assert config.monitors[0].phrase_regex == "ALERT"
