"""Utilities for validating configuration field values."""

from __future__ import annotations

import re


def validate_regex(label: str, value: str) -> None:
    """Validate that *value* is a compilable regular expression.

    Args:
        label: Human-readable field name used in the error message.
        value: The regex string to validate.

    Raises:
        ValueError: If *value* is not a valid regular expression.
    """
    try:
        re.compile(value)
    except re.error as exc:
        raise ValueError(f"{label} invalid regex: {exc}") from exc


def validate_email_address(label: str, value: str) -> None:
    """Validate that *value* is a syntactically valid e-mail address.

    Args:
        label: Human-readable field name used in the error message.
        value: The e-mail string to validate.

    Raises:
        ValueError: If *value* does not look like a valid e-mail address.
    """
    if "@" not in value or value.startswith("@") or value.endswith("@"):
        raise ValueError(f"{label} must be a valid email address")
    local, _, domain = value.partition("@")
    if not local or not domain or "." not in domain:
        raise ValueError(f"{label} must be a valid email address")
