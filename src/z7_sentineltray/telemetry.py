"""Thin telemetry helpers for writing JSON event records atomically."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .io_utils import atomic_write_text as _atomic_write_text


@dataclass
class JsonWriter:
    """Write JSON payloads to a file path via atomic rename.

    Attributes:
        path: Destination file that will be overwritten on each :meth:`write`.
    """

    path: Path

    def write(self, payload: dict[str, Any]) -> None:
        """Serialise *payload* to JSON and atomically write it to :attr:`path`.

        Args:
            payload: Mapping to serialise.
        """
        payload_json = json.dumps(payload, ensure_ascii=True, indent=2)
        atomic_write_text(self.path, payload_json, encoding="utf-8")


def atomic_write_text(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    """Re-export :func:`io_utils.atomic_write_text` for backward compatibility.

    Args:
        path: Destination file path.
        content: Text content to write.
        encoding: Character encoding (default ``utf-8``).
    """
    _atomic_write_text(path, content, encoding=encoding)
