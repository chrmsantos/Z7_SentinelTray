"""Atomic file I/O helpers and safe JSON/text read utilities."""

from __future__ import annotations

import contextlib
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)


def atomic_write_text(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    """Write *content* to *path* atomically using a temporary file + rename.

    The directory is created if it does not exist.  The write is fsynced
    before the rename so data survives a crash or power failure.

    Args:
        path: Destination file path.
        content: Text content to write.
        encoding: Character encoding (default ``utf-8``).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name = f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    temp_path = path.with_name(temp_name)
    try:
        with temp_path.open("w", encoding=encoding, newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            with contextlib.suppress(OSError):
                temp_path.unlink()


def read_text_safe(
    path: Path,
    *,
    encoding: str = "utf-8",
    default: str = "",
    context: str | None = None,
) -> str:
    """Read *path* as text, returning *default* on ``FileNotFoundError``.

    Other ``OSError`` subclasses are logged at WARNING level and *default*
    is returned.

    Args:
        path: File to read.
        encoding: Character encoding (default ``utf-8``).
        default: Value to return when the file is missing or unreadable.
        context: Optional label for log messages; defaults to ``str(path)``.

    Returns:
        File contents or *default*.
    """
    try:
        return path.read_text(encoding=encoding)
    except FileNotFoundError:
        return default
    except Exception as exc:
        label = context or str(path)
        LOGGER.warning(
            "Failed to read %s: %s",
            label,
            exc,
            extra={"category": "io"},
        )
        return default


def read_json_safe(
    path: Path,
    *,
    default: Any,  # noqa: ANN401
    context: str | None = None,
) -> Any:  # noqa: ANN401
    """Read and parse a JSON file, returning *default* on any failure.

    Args:
        path: JSON file to read.
        default: Value to return when the file is missing, empty, or invalid.
        context: Optional label for log messages; defaults to ``str(path)``.

    Returns:
        Parsed JSON value or *default*.
    """
    text = read_text_safe(path, default="", context=context)
    if not text.strip():
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        label = context or str(path)
        LOGGER.warning(
            "Failed to parse JSON from %s: %s",
            label,
            exc,
            extra={"category": "io"},
        )
        return default
