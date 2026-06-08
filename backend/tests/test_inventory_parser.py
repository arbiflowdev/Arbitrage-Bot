"""Unit tests for the pure inventory upload parser (TXT + CSV)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.fulfillment.inventory_parser import parse_inventory


def test_txt_one_code_per_line_trims_and_skips_blanks() -> None:
    content = "  KEY-1 \n\nKEY-2\n   \nKEY-3\n"
    result = parse_inventory(content, "txt")
    assert [c.code for c in result.items] == ["KEY-1", "KEY-2", "KEY-3"]
    assert result.skipped_blank == 2
    assert result.duplicates == 0


def test_txt_dedupes_repeated_codes_within_batch() -> None:
    content = "KEY-1\nKEY-2\nKEY-1\nKEY-2\nKEY-3\n"
    result = parse_inventory(content, "txt")
    assert [c.code for c in result.items] == ["KEY-1", "KEY-2", "KEY-3"]
    assert result.duplicates == 2


def test_csv_parses_code_and_optional_columns() -> None:
    content = (
        "code,region,platform,source_cost,currency,notes\n"
        "KEY-1,EU,Steam,9.50,EUR,first\n"
        "KEY-2,US,Steam,,USD,\n"
    )
    result = parse_inventory(content, "csv")
    assert len(result.items) == 2
    first = result.items[0]
    assert first.code == "KEY-1"
    assert first.region == "EU"
    assert first.platform == "Steam"
    assert first.source_cost == Decimal("9.50")
    assert first.currency == "EUR"
    assert first.notes == "first"
    second = result.items[1]
    assert second.code == "KEY-2"
    assert second.source_cost is None
    assert second.currency == "USD"
    assert second.notes is None


def test_csv_requires_a_code_column() -> None:
    content = "region,platform\nEU,Steam\n"
    with pytest.raises(ValueError, match="code"):
        parse_inventory(content, "csv")


def test_csv_skips_rows_with_blank_code_and_dedupes() -> None:
    # Row 2 has an empty code cell -> skipped; row 3 repeats KEY-1 -> duplicate.
    content = "code,region\nKEY-1,EU\n,US\nKEY-1,FR\nKEY-2,DE\n"
    result = parse_inventory(content, "csv")
    assert [c.code for c in result.items] == ["KEY-1", "KEY-2"]
    assert result.duplicates == 1
    assert result.skipped_blank == 1


def test_unknown_format_raises() -> None:
    with pytest.raises(ValueError, match="format"):
        parse_inventory("KEY-1", "xlsx")
