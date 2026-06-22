"""Tests for _build_alert_message — delta enrichment on alert notifications."""

from __future__ import annotations

from z7_sentineltray.app import _build_alert_message


def test_no_delta_when_count_unchanged() -> None:
    result = _build_alert_message("5 PROPOSITURAS NÃO RECEBIDAS", 5)
    assert result == "5 PROPOSITURAS NÃO RECEBIDAS"


def test_positive_delta_appended() -> None:
    result = _build_alert_message("8 PROPOSITURAS NÃO RECEBIDAS", 5)
    assert "Variação" in result
    assert "+3" in result
    assert result.startswith("8 PROPOSITURAS NÃO RECEBIDAS")


def test_negative_delta_appended() -> None:
    result = _build_alert_message("3 PROPOSITURAS NÃO RECEBIDAS", 5)
    assert "Variação" in result
    assert "-2" in result


def test_no_delta_when_text_has_no_leading_number() -> None:
    result = _build_alert_message("PROPOSITURAS NÃO RECEBIDAS", 5)
    assert result == "PROPOSITURAS NÃO RECEBIDAS"


def test_no_delta_when_no_previous_number() -> None:
    result = _build_alert_message("10 PROPOSITURAS NÃO RECEBIDAS", None)
    assert result == "10 PROPOSITURAS NÃO RECEBIDAS"


def test_no_delta_on_empty_text() -> None:
    result = _build_alert_message("", None)
    assert result == ""


def test_delta_one_new_item() -> None:
    result = _build_alert_message("1 PROPOSITURA NÃO RECEBIDA", 0)
    assert "+1" in result
