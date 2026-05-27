"""Tests for the updater module."""

from __future__ import annotations

import unittest

from z7_sentineltray.updater import parse_version


class TestUpdater(unittest.TestCase):
    """Test case for update system functions."""

    def test_parse_version_standard(self) -> None:
        """Test parsing standard version strings."""
        assert parse_version("6.1.5") == (6, 1, 5)
        assert parse_version("1.0.0") == (1, 0, 0)

    def test_parse_version_v_prefix(self) -> None:
        """Test parsing version strings with 'v' or 'V' prefix."""
        assert parse_version("v6.2.0") == (6, 2, 0)
        assert parse_version("V12.3.4") == (12, 3, 4)

    def test_parse_version_with_metadata(self) -> None:
        """Test parsing version strings with alpha/beta/metadata suffixes."""
        assert parse_version("6.2.0-beta.1") == (6, 2, 0, 1)
        assert parse_version("v6.2.0-rc2") == (6, 2, 0, 2)

    def test_version_comparison(self) -> None:
        """Test direct tuple comparison of parsed versions."""
        assert parse_version("6.2.0") > parse_version("6.1.5")
        assert parse_version("v6.2.0") > parse_version("v6.1.5")
        assert parse_version("v10.0.0") > parse_version("v9.9.9")
        assert parse_version("6.1.5") == parse_version("v6.1.5")
