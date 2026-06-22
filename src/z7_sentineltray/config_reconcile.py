"""Config template reconciliation: merge, diff, and apply YAML templates."""

from __future__ import annotations

import hashlib
import io
import logging
from collections.abc import MutableMapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .config import get_project_root

try:
    from ruamel.yaml import YAML  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    YAML = None

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class TemplateReconcileSummary:
    """Result of a config template reconciliation run."""

    added: int
    changed: int
    template_sha256: str | None
    config_sha256: str | None
    applied: bool
    skipped_reason: str | None = None


def _load_yaml_mapping(text: str) -> dict[str, Any]:
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise TypeError("Config must be a mapping")
    return data


def _merge_dicts(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged


def _merge_into_template(
    template: MutableMapping[str, Any], legacy: MutableMapping[str, Any]
) -> None:
    for key, value in legacy.items():
        if (
            key in template
            and isinstance(template.get(key), MutableMapping)
            and isinstance(value, MutableMapping)
        ):
            _merge_into_template(template[key], value)
        else:
            template[key] = value


def _get_ruamel_yaml() -> YAML | None:
    if YAML is None:
        return None
    yaml_rt = YAML()
    yaml_rt.preserve_quotes = True
    yaml_rt.indent(mapping=2, sequence=4, offset=2)
    return yaml_rt


def read_template_config_text(project_root: Path | None = None) -> str | None:
    """Read the bundled config template text, or return ``None`` if unavailable."""
    try:
        root = project_root or get_project_root()
        template_path = root / "templates" / "local" / "config.local.yaml"
        if template_path.exists():
            return template_path.read_text(encoding="utf-8")
    except Exception as exc:
        LOGGER.warning("Failed to read config template: %s", exc)
    return None


def apply_template_to_config_text(legacy_text: str, template_text: str | None) -> str:
    """Merge *legacy_text* values into *template_text*, preserving template structure."""
    if not template_text:
        return legacy_text
    try:
        yaml_rt = _get_ruamel_yaml()
        if yaml_rt is not None:
            template_data = yaml_rt.load(template_text) or {}
            legacy_data = yaml_rt.load(legacy_text) or {}
            if not isinstance(template_data, MutableMapping) or not isinstance(
                legacy_data, MutableMapping
            ):
                raise ValueError("Config must be a mapping")
            _merge_into_template(template_data, legacy_data)
            buffer = io.StringIO()
            yaml_rt.dump(template_data, buffer)
            return buffer.getvalue()
        template_data = _load_yaml_mapping(template_text)
        legacy_data = _load_yaml_mapping(legacy_text)
        merged = _merge_dicts(template_data, legacy_data)
        return yaml.safe_dump(merged, sort_keys=False, allow_unicode=True)
    except Exception as exc:
        LOGGER.warning("Failed to merge config template: %s", exc)
        return legacy_text


def hash_text(text: str) -> str:
    """Return the SHA-256 hex digest of *text*."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_current_config_text(config_path: Path) -> str:
    """Read and return the text of the config file at *config_path*."""
    return config_path.read_text(encoding="utf-8")


def _diff_counts(old: Any, new: Any) -> tuple[int, int]:  # noqa: ANN401
    added = 0
    changed = 0
    if isinstance(old, dict) and isinstance(new, dict):
        for key, new_value in new.items():
            if key not in old:
                added += 1
            else:
                old_value = old[key]
                if isinstance(old_value, dict) and isinstance(new_value, dict):
                    sub_added, sub_changed = _diff_counts(old_value, new_value)
                    added += sub_added
                    changed += sub_changed
                elif old_value != new_value:
                    changed += 1
        return added, changed
    return (0, 1) if old != new else (0, 0)


def ensure_local_config_from_template(
    config_path: Path,
    *,
    template_text: str | None = None,
    logger: logging.Logger | None = None,
) -> bool:
    """Write *template_text* to *config_path* if the file is absent or empty."""
    if config_path.exists():
        try:
            if config_path.read_text(encoding="utf-8").strip():
                return False
        except Exception:
            return False
    if not template_text:
        return False
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(template_text, encoding="utf-8")
    (logger or LOGGER).info(
        "Local config created from template",
        extra={"category": "config", "config_path": str(config_path)},
    )
    return True


def reconcile_template_config(
    config_path: Path,
    *,
    template_text: str | None = None,
    dry_run: bool,
    logger: logging.Logger | None = None,
) -> TemplateReconcileSummary:
    """Reconcile *config_path* with the bundled template, adding new keys."""
    if template_text is None:
        template_text = read_template_config_text()
    if not template_text:
        return TemplateReconcileSummary(
            added=0,
            changed=0,
            template_sha256=None,
            config_sha256=None,
            applied=False,
            skipped_reason="template_missing",
        )
    if not config_path.exists():
        return TemplateReconcileSummary(
            added=0,
            changed=0,
            template_sha256=hash_text(template_text),
            config_sha256=None,
            applied=False,
            skipped_reason="config_missing",
        )
    legacy_text = load_current_config_text(config_path)
    merged_text = apply_template_to_config_text(legacy_text, template_text)
    legacy_data = _load_yaml_mapping(legacy_text)
    merged_data = _load_yaml_mapping(merged_text)
    added, changed = _diff_counts(legacy_data, merged_data)
    template_hash = hash_text(template_text)
    merged_hash = hash_text(merged_text)

    if added == 0 and changed == 0:
        return TemplateReconcileSummary(
            added=0,
            changed=0,
            template_sha256=template_hash,
            config_sha256=merged_hash,
            applied=False,
        )

    if dry_run:
        return TemplateReconcileSummary(
            added=added,
            changed=changed,
            template_sha256=template_hash,
            config_sha256=merged_hash,
            applied=False,
        )

    config_path.write_text(merged_text, encoding="utf-8")

    (logger or LOGGER).info(
        "Config template reconciled",
        extra={
            "category": "config",
            "template_sha256": template_hash,
            "config_sha256": merged_hash,
            "added": added,
            "changed": changed,
        },
    )
    return TemplateReconcileSummary(
        added=added,
        changed=changed,
        template_sha256=template_hash,
        config_sha256=merged_hash,
        applied=True,
    )
