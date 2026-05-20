"""Application configuration loading, validation, and dataclass definitions."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, cast

import yaml

from .dpapi_utils import load_secret
from .path_utils import ensure_under_root, resolve_log_path, resolve_sensitive_path
from .validation_utils import validate_email_address, validate_regex

MAX_LOG_FILES = 3

CURRENT_CONFIG_VERSION = 1

LOGGER = logging.getLogger(__name__)

_CONFIG_MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {}

_DEFAULT_CONFIG_VALUES: dict[str, Any] = {
    "send_repeated_matches": True,
    "min_repeat_seconds": 0,
    "error_notification_cooldown_seconds": 300,
    "window_error_backoff_base_seconds": 5,
    "window_error_backoff_max_seconds": 120,
    "window_error_circuit_threshold": 3,
    "window_error_circuit_seconds": 300,
    "email_queue_file": "logs/email_queue.json",
    "email_queue_max_items": 500,
    "email_queue_max_age_seconds": 86400,
    "email_queue_max_attempts": 10,
    "email_queue_retry_base_seconds": 30,
    "config_version": CURRENT_CONFIG_VERSION,
    "pause_on_user_active": True,
    "pause_idle_threshold_seconds": 180,
    "healthcheck_send_on_error_only": True,
}


def _migrate_config_data(data: dict[str, Any]) -> dict[str, Any]:
    version_raw = data.get("config_version", CURRENT_CONFIG_VERSION)
    try:
        version = int(version_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("config_version must be an integer") from exc
    if version > CURRENT_CONFIG_VERSION:
        raise ValueError(
            f"config_version is newer than supported: {version} > {CURRENT_CONFIG_VERSION}"
        )
    if version < 1:
        raise ValueError("config_version must be >= 1")
    migrated = dict(data)
    while version < CURRENT_CONFIG_VERSION:
        migrate = _CONFIG_MIGRATIONS.get(version)
        if migrate is None:
            raise ValueError(f"Unsupported config_version {version}: no migration available")
        migrated = migrate(migrated)
        version = int(migrated.get("config_version", version + 1))
    migrated["config_version"] = CURRENT_CONFIG_VERSION
    return migrated


def _apply_config_defaults(data: dict[str, Any]) -> dict[str, Any]:
    missing: list[str] = []
    updated = dict(data)
    for key, value in _DEFAULT_CONFIG_VALUES.items():
        if key not in updated:
            updated[key] = value
            missing.append(key)
    if missing:
        LOGGER.warning(
            "Applied defaults for missing config keys: %s",
            ", ".join(sorted(missing)),
        )
    return updated


def _get_project_root_from_file() -> Path:
    return Path(__file__).resolve().parents[2]


def get_user_data_dir() -> Path:
    """Return the user-specific data directory, respecting ``Z7_SENTINELTRAY_DATA_DIR``."""
    override = os.environ.get("Z7_SENTINELTRAY_DATA_DIR")
    if override:
        return Path(override)
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        return Path(local_appdata) / "ZWave" / "Tmp" / "Z7_SentinelTray" / "Config"
    user_profile = os.environ.get("USERPROFILE")
    if user_profile:
        return (
            Path(user_profile)
            / "AppData"
            / "Local"
            / "ZWave"
            / "Tmp"
            / "Z7_SentinelTray"
            / "Config"
        )
    return Path.home() / "AppData" / "Local" / "ZWave" / "Tmp" / "Z7_SentinelTray" / "Config"


def get_user_log_dir() -> Path:
    """Return the user-specific log directory."""
    return get_user_data_dir() / "logs"


def get_project_root() -> Path:
    """Return the project root, respecting ``Z7_SENTINELTRAY_ROOT``."""
    override = os.environ.get("Z7_SENTINELTRAY_ROOT")
    if override:
        return Path(override)
    return _get_project_root_from_file()


@dataclass(frozen=True)
class EmailConfig:
    """Immutable SMTP/email delivery configuration for a single monitor."""

    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password: str
    from_address: str
    to_addresses: list[str]
    use_tls: bool
    timeout_seconds: int
    subject: str
    retry_attempts: int
    retry_backoff_seconds: int


@dataclass(frozen=True)
class MonitorConfig:
    """Window-match and email settings for one monitor target."""

    window_title_regex: str
    phrase_regex: str
    email: EmailConfig


@dataclass(frozen=True)
class AppConfig:
    """Fully validated, immutable application-wide configuration."""

    poll_interval_seconds: int
    healthcheck_interval_seconds: int
    error_backoff_base_seconds: int
    error_backoff_max_seconds: int
    debounce_seconds: int
    max_history: int
    state_file: str
    log_file: str
    log_level: str
    log_console_level: str
    log_console_enabled: bool
    log_max_bytes: int
    log_backup_count: int
    log_run_files_keep: int
    telemetry_file: str
    allow_window_restore: bool
    log_only_mode: bool
    send_repeated_matches: bool
    min_repeat_seconds: int = 0
    error_notification_cooldown_seconds: int = 300
    window_error_backoff_base_seconds: int = 5
    window_error_backoff_max_seconds: int = 120
    window_error_circuit_threshold: int = 3
    window_error_circuit_seconds: int = 300
    email_queue_file: str = "logs/email_queue.json"
    email_queue_max_items: int = 500
    email_queue_max_age_seconds: int = 86400
    email_queue_max_attempts: int = 10
    email_queue_retry_base_seconds: int = 30
    pause_on_user_active: bool = True
    pause_idle_threshold_seconds: int = 180
    healthcheck_send_on_error_only: bool = True
    monitors: list[MonitorConfig] = field(default_factory=lambda: cast(list[MonitorConfig], []))
    config_version: int = 1


def _get_required(data: dict[str, Any], key: str) -> Any:  # noqa: ANN401
    if key not in data:
        raise ValueError(f"Missing required config key: {key}")
    return data[key]


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Failed to read config file: {path}") from exc
    try:
        raw: object = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML in config file: {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise TypeError("Config must be a mapping")
    return cast(dict[str, Any], raw)


def _merge_dicts(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dicts(
                cast(dict[str, Any], merged.get(key)),
                cast(dict[str, Any], value),
            )
        else:
            merged[key] = value
    return merged


def _env_override(name: str, monitor_index: int | None) -> str | None:
    base_key = f"Z7_SENTINELTRAY_{name}"
    if monitor_index is not None:
        indexed = os.environ.get(f"{base_key}_{monitor_index}")
        if indexed:
            return indexed
    return os.environ.get(base_key)


def _build_email_config(
    email_data: dict[str, Any],
    *,
    monitor_index: int | None,
) -> EmailConfig:
    to_raw = _get_required(email_data, "to_addresses")
    if isinstance(to_raw, str):
        to_addresses = [item.strip() for item in to_raw.split(",") if item.strip()]
    elif isinstance(to_raw, list):
        to_addresses = [
            str(item).strip() for item in cast(list[object], to_raw) if str(item).strip()
        ]
    else:
        raise TypeError("email.to_addresses must be a list or comma-separated string")

    smtp_username = str(_get_required(email_data, "smtp_username"))
    if "smtp_password" in email_data:
        smtp_password = str(email_data.get("smtp_password") or "")
        if smtp_password:
            LOGGER.warning(
                "Plaintext smtp_password found in config for monitor %s; "
                "remove it and use the DPAPI-encrypted store instead",
                monitor_index or 0,
                extra={"category": "config"},
            )
    else:
        smtp_password = ""
    env_password = _env_override("SMTP_PASSWORD", monitor_index)
    if env_password:
        smtp_password = env_password
    if not smtp_password:
        index = monitor_index or 0
        secret_path = get_user_data_dir() / f"smtp_password_{index}.dpapi"
        try:
            stored_password = load_secret(secret_path)
        except Exception:
            stored_password = None
        if stored_password:
            smtp_password = stored_password
    if not smtp_password.strip():
        LOGGER.info(
            "SMTP password missing for monitor %s; will prompt in CLI",
            monitor_index or 0,
        )

    return EmailConfig(
        smtp_host=str(_get_required(email_data, "smtp_host")),
        smtp_port=int(_get_required(email_data, "smtp_port")),
        smtp_username=smtp_username,
        smtp_password=smtp_password,
        from_address=str(_get_required(email_data, "from_address")),
        to_addresses=to_addresses,
        use_tls=bool(_get_required(email_data, "use_tls")),
        timeout_seconds=int(_get_required(email_data, "timeout_seconds")),
        subject=str(_get_required(email_data, "subject")),
        retry_attempts=int(_get_required(email_data, "retry_attempts")),
        retry_backoff_seconds=int(_get_required(email_data, "retry_backoff_seconds")),
    )


def _build_config(data: dict[str, Any]) -> AppConfig:  # noqa: C901
    data = _apply_config_defaults(_migrate_config_data(data))
    monitors: list[MonitorConfig] = []
    monitors_data = data.get("monitors")
    if not isinstance(monitors_data, list) or not monitors_data:
        raise ValueError("monitors must be a non-empty list")
    monitors_list = cast(list[object], monitors_data)
    for index, entry in enumerate(monitors_list, start=1):
        if not isinstance(entry, dict):
            raise TypeError("monitors entries must be objects")
        entry_map = cast(dict[str, Any], entry)
        monitor_email = _build_email_config(
            cast(dict[str, Any], _get_required(entry_map, "email")),
            monitor_index=index,
        )
        monitors.append(
            MonitorConfig(
                window_title_regex=str(_get_required(entry_map, "window_title_regex")),
                phrase_regex=str(_get_required(entry_map, "phrase_regex")),
                email=monitor_email,
            )
        )

    log_backup_count = int(_get_required(data, "log_backup_count"))
    log_run_files_keep = int(_get_required(data, "log_run_files_keep"))
    if log_backup_count > MAX_LOG_FILES:
        logging.getLogger(__name__).warning(
            "log_backup_count capped at %s (requested %s)",
            MAX_LOG_FILES,
            log_backup_count,
        )
        log_backup_count = MAX_LOG_FILES
    if log_run_files_keep > MAX_LOG_FILES:
        logging.getLogger(__name__).warning(
            "log_run_files_keep capped at %s (requested %s)",
            MAX_LOG_FILES,
            log_run_files_keep,
        )
        log_run_files_keep = MAX_LOG_FILES

    defaults_applied: list[str] = []
    if "send_repeated_matches" not in data:
        defaults_applied.append("send_repeated_matches")
    if "min_repeat_seconds" not in data:
        defaults_applied.append("min_repeat_seconds")
    if "error_notification_cooldown_seconds" not in data:
        defaults_applied.append("error_notification_cooldown_seconds")
    if "window_error_backoff_base_seconds" not in data:
        defaults_applied.append("window_error_backoff_base_seconds")
    if "window_error_backoff_max_seconds" not in data:
        defaults_applied.append("window_error_backoff_max_seconds")
    if "window_error_circuit_threshold" not in data:
        defaults_applied.append("window_error_circuit_threshold")
    if "window_error_circuit_seconds" not in data:
        defaults_applied.append("window_error_circuit_seconds")
    if "email_queue_file" not in data:
        defaults_applied.append("email_queue_file")
    if "email_queue_max_items" not in data:
        defaults_applied.append("email_queue_max_items")
    if "email_queue_max_age_seconds" not in data:
        defaults_applied.append("email_queue_max_age_seconds")
    if "email_queue_max_attempts" not in data:
        defaults_applied.append("email_queue_max_attempts")
    if "email_queue_retry_base_seconds" not in data:
        defaults_applied.append("email_queue_retry_base_seconds")
    if "pause_on_user_active" not in data:
        defaults_applied.append("pause_on_user_active")
    if "pause_idle_threshold_seconds" not in data:
        defaults_applied.append("pause_idle_threshold_seconds")

    config = AppConfig(
        poll_interval_seconds=int(_get_required(data, "poll_interval_seconds")),
        healthcheck_interval_seconds=int(_get_required(data, "healthcheck_interval_seconds")),
        error_backoff_base_seconds=int(_get_required(data, "error_backoff_base_seconds")),
        error_backoff_max_seconds=int(_get_required(data, "error_backoff_max_seconds")),
        debounce_seconds=int(_get_required(data, "debounce_seconds")),
        max_history=int(_get_required(data, "max_history")),
        state_file=str(_get_required(data, "state_file")),
        log_file=str(_get_required(data, "log_file")),
        log_level=str(_get_required(data, "log_level")),
        log_console_level=str(_get_required(data, "log_console_level")),
        log_console_enabled=bool(_get_required(data, "log_console_enabled")),
        log_max_bytes=int(_get_required(data, "log_max_bytes")),
        log_backup_count=log_backup_count,
        log_run_files_keep=log_run_files_keep,
        telemetry_file=str(_get_required(data, "telemetry_file")),
        allow_window_restore=bool(_get_required(data, "allow_window_restore")),
        log_only_mode=bool(_get_required(data, "log_only_mode")),
        send_repeated_matches=bool(data.get("send_repeated_matches", True)),
        min_repeat_seconds=int(data.get("min_repeat_seconds", 0)),
        error_notification_cooldown_seconds=int(
            data.get("error_notification_cooldown_seconds", 300)
        ),
        window_error_backoff_base_seconds=int(data.get("window_error_backoff_base_seconds", 5)),
        window_error_backoff_max_seconds=int(data.get("window_error_backoff_max_seconds", 120)),
        window_error_circuit_threshold=int(data.get("window_error_circuit_threshold", 3)),
        window_error_circuit_seconds=int(data.get("window_error_circuit_seconds", 300)),
        email_queue_file=str(data.get("email_queue_file", "logs/email_queue.json")),
        email_queue_max_items=int(data.get("email_queue_max_items", 500)),
        email_queue_max_age_seconds=int(data.get("email_queue_max_age_seconds", 86400)),
        email_queue_max_attempts=int(data.get("email_queue_max_attempts", 10)),
        email_queue_retry_base_seconds=int(data.get("email_queue_retry_base_seconds", 30)),
        pause_on_user_active=bool(data.get("pause_on_user_active", True)),
        pause_idle_threshold_seconds=int(data.get("pause_idle_threshold_seconds", 180)),
        healthcheck_send_on_error_only=bool(data.get("healthcheck_send_on_error_only", True)),
        monitors=monitors,
        config_version=int(data.get("config_version", 1)),
    )
    config = _apply_sensitive_path_policy(config)
    _validate_config(config)
    if defaults_applied:
        logging.getLogger(__name__).info(
            "Defaults applied for missing keys: %s",
            ", ".join(defaults_applied),
        )
    return config


def _apply_sensitive_path_policy(config: AppConfig) -> AppConfig:
    base = get_user_data_dir()
    log_root = get_user_log_dir()

    return replace(
        config,
        state_file=resolve_sensitive_path(base, config.state_file),
        log_file=resolve_log_path(base, log_root, config.log_file),
        telemetry_file=resolve_log_path(base, log_root, config.telemetry_file),
        email_queue_file=resolve_log_path(base, log_root, config.email_queue_file),
    )


def _is_valid_log_level(level: str) -> bool:
    level_name = str(level).upper()
    return level_name in logging.getLevelNamesMapping()


def _validate_config(config: AppConfig) -> None:  # noqa: C901
    log_root = get_user_log_dir().resolve()

    if config.poll_interval_seconds < 1:
        raise ValueError("poll_interval_seconds must be >= 1")
    if config.healthcheck_interval_seconds < 1:
        raise ValueError("healthcheck_interval_seconds must be >= 1")
    if config.error_backoff_base_seconds < 1:
        raise ValueError("error_backoff_base_seconds must be >= 1")
    if config.error_backoff_max_seconds < config.error_backoff_base_seconds:
        raise ValueError("error_backoff_max_seconds must be >= error_backoff_base_seconds")
    if config.debounce_seconds < 0:
        raise ValueError("debounce_seconds must be >= 0")
    if config.min_repeat_seconds < 0:
        raise ValueError("min_repeat_seconds must be >= 0")
    if config.max_history < 1:
        raise ValueError("max_history must be >= 1")
    if not config.state_file:
        raise ValueError("state_file is required")
    if not config.log_file:
        raise ValueError("log_file is required")
    if config.log_max_bytes < 1024:
        raise ValueError("log_max_bytes must be >= 1024")
    if config.log_backup_count < 0:
        raise ValueError("log_backup_count must be >= 0")
    if config.log_run_files_keep < 1:
        raise ValueError("log_run_files_keep must be >= 1")
    if not _is_valid_log_level(config.log_level):
        raise ValueError("log_level must be a valid logging level")
    if not _is_valid_log_level(config.log_console_level):
        raise ValueError("log_console_level must be a valid logging level")
    if not config.telemetry_file:
        raise ValueError("telemetry_file is required")
    ensure_under_root(log_root, config.log_file, "log_file")
    ensure_under_root(log_root, config.telemetry_file, "telemetry_file")
    ensure_under_root(log_root, config.email_queue_file, "email_queue_file")
    if config.error_notification_cooldown_seconds < 0:
        raise ValueError("error_notification_cooldown_seconds must be >= 0")
    if config.window_error_backoff_base_seconds < 1:
        raise ValueError("window_error_backoff_base_seconds must be >= 1")
    if config.window_error_backoff_max_seconds < config.window_error_backoff_base_seconds:
        raise ValueError(
            "window_error_backoff_max_seconds must be >= window_error_backoff_base_seconds"
        )
    if config.window_error_circuit_threshold < 1:
        raise ValueError("window_error_circuit_threshold must be >= 1")
    if config.window_error_circuit_seconds < 0:
        raise ValueError("window_error_circuit_seconds must be >= 0")
    if config.email_queue_max_items < 1:
        raise ValueError("email_queue_max_items must be >= 1")
    if config.email_queue_max_age_seconds < 0:
        raise ValueError("email_queue_max_age_seconds must be >= 0")
    if config.email_queue_max_attempts < 0:
        raise ValueError("email_queue_max_attempts must be >= 0")
    if config.email_queue_retry_base_seconds < 0:
        raise ValueError("email_queue_retry_base_seconds must be >= 0")
    if config.pause_on_user_active and config.pause_idle_threshold_seconds < 1:
        raise ValueError(
            "pause_idle_threshold_seconds must be >= 1 when pause_on_user_active is enabled"
        )
    if config.config_version < 1:
        raise ValueError("config_version must be >= 1")
    if config.monitors:
        for monitor in config.monitors:
            if monitor.window_title_regex:
                validate_regex("monitors.window_title_regex", monitor.window_title_regex)
            if monitor.phrase_regex:
                validate_regex("monitors.phrase_regex", monitor.phrase_regex)
            if not (1 <= monitor.email.smtp_port <= 65535):
                raise ValueError("monitors.email.smtp_port must be between 1 and 65535")
            if not monitor.email.smtp_host:
                raise ValueError("monitors.email.smtp_host is required")
            if not monitor.email.smtp_username:
                raise ValueError("monitors.email.smtp_username is required")
            if not monitor.email.from_address:
                raise ValueError("monitors.email.from_address is required")
            if not monitor.email.to_addresses:
                raise ValueError("monitors.email.to_addresses is required")
            validate_email_address("monitors.email.from_address", monitor.email.from_address)
            for address in monitor.email.to_addresses:
                validate_email_address("monitors.email.to_addresses", address)


def load_config(path: str) -> AppConfig:
    """Load and validate an ``AppConfig`` from a YAML file at *path*."""
    data = _load_yaml(Path(path))
    return _build_config(data)


def load_config_with_override(base_path: str, override_path: str) -> AppConfig:
    """Load and merge two YAML config files, then validate the result."""
    base = _load_yaml(Path(base_path))
    override = _load_yaml(Path(override_path))
    merged = _merge_dicts(base, override)
    return _build_config(merged)
