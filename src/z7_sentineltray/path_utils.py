"""Utilities for safe path resolution and root-boundary enforcement."""

from __future__ import annotations

from pathlib import Path


def resolve_sensitive_path(base: Path, value: str) -> str:
    """Resolve *value* relative to *base*, keeping it inside *base*.

    Absolute paths that do not fall under *base* are re-rooted to
    ``base / filename`` so user-supplied paths cannot escape the data dir.

    Args:
        base: Allowed root directory.
        value: Raw path string from configuration.

    Returns:
        Absolute path string guaranteed to be under *base*.
    """
    candidate = Path(value)
    if not candidate.is_absolute():
        return str(base / candidate)
    try:
        if candidate.resolve().is_relative_to(base.resolve()):
            return str(candidate)
    except OSError:
        pass
    return str(base / candidate.name)


def resolve_log_path(base: Path, log_root: Path, value: str) -> str:
    """Resolve a log-file path, confining it to *log_root* when absolute.

    Args:
        base: Data directory used as base for relative paths.
        log_root: Allowed root for absolute log paths.
        value: Raw path string from configuration.

    Returns:
        Absolute path string for the log file.
    """
    candidate = Path(value)
    if not candidate.is_absolute():
        return str(base / candidate)
    try:
        if candidate.resolve().is_relative_to(log_root.resolve()):
            return str(candidate)
    except OSError:
        pass
    return str(log_root / candidate.name)


def ensure_under_root(log_root: Path, path_value: str, label: str) -> None:
    """Assert that *path_value* resolves to a location inside *log_root*.

    Args:
        log_root: Required ancestor directory.
        path_value: Path string to validate.
        label: Human-readable name for error messages.

    Raises:
        ValueError: If *path_value* resolves outside *log_root*.
    """
    try:
        resolved = Path(path_value).resolve()
        if not resolved.is_relative_to(log_root):
            raise ValueError(f"{label} must be under {log_root}")
    except OSError as exc:
        raise ValueError(f"{label} must be under {log_root}") from exc
