from __future__ import annotations

from pathlib import Path

import yaml

from z7_sentineltray.config_reconcile import (
    apply_template_to_config_text,
    ensure_local_config_from_template,
    reconcile_template_config,
)


def test_ensure_local_config_from_template_creates_file(tmp_path: Path) -> None:
    config_path = tmp_path / "config.local.yaml"
    template_text = "log_level: 'INFO'\n"

    created = ensure_local_config_from_template(config_path, template_text=template_text)

    assert created is True
    assert config_path.exists()
    assert config_path.read_text(encoding="utf-8") == template_text


def test_ensure_local_config_from_template_refuses_non_empty(tmp_path: Path) -> None:
    config_path = tmp_path / "config.local.yaml"
    config_path.write_text("log_level: 'DEBUG'\n", encoding="utf-8")
    template_text = "log_level: 'INFO'\n"

    created = ensure_local_config_from_template(config_path, template_text=template_text)

    assert created is False
    assert config_path.read_text(encoding="utf-8") == "log_level: 'DEBUG'\n"


def test_reconcile_template_config_applies_merge(tmp_path: Path) -> None:
    config_path = tmp_path / "config.local.yaml"
    template_text = (
        "log_level: 'INFO'\nemail: {smtp_host: ''}\ntelemetry_file: 'logs/telemetry.json'\n"
    )
    legacy_text = "log_level: 'DEBUG'\nemail: {smtp_host: 'smtp.local'}\n"

    config_path.write_text(legacy_text, encoding="utf-8")

    summary = reconcile_template_config(
        config_path,
        template_text=template_text,
        dry_run=False,
    )

    assert summary.applied is True
    merged_text = config_path.read_text(encoding="utf-8")
    merged_data = yaml.safe_load(merged_text)
    assert merged_data["log_level"] == "DEBUG"
    assert merged_data["email"]["smtp_host"] == "smtp.local"
    assert merged_data["telemetry_file"] == "logs/telemetry.json"


def test_apply_template_to_config_text_keeps_template_defaults() -> None:
    template = "log_level: 'INFO'\nemail: {smtp_host: ''}\n"
    legacy = "log_level: 'DEBUG'\n"

    merged = apply_template_to_config_text(legacy, template)

    merged_data = yaml.safe_load(merged)
    assert merged_data["log_level"] == "DEBUG"
    assert "email" in merged_data
