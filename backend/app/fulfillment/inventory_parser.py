"""Pure parser for inventory uploads (TXT + CSV).

Turns an uploaded blob of deliverable codes/keys into validated, de-duplicated
:class:`ParsedCode` records. No database, no I/O — so it is trivially unit
tested and reused by both the upload API and bulk import tooling.

- **TXT** — one code per line. Blank lines are skipped; surrounding whitespace
  is trimmed.
- **CSV** — a header row with a required ``code`` column plus optional
  ``region``, ``platform``, ``source_cost``, ``currency`` and ``notes`` columns.

Duplicate codes *within a single upload* are dropped (first occurrence wins) and
counted, so an operator can see exactly what was accepted versus ignored.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

SUPPORTED_FORMATS = ("txt", "csv")


@dataclass(slots=True)
class ParsedCode:
    code: str
    region: str | None = None
    platform: str | None = None
    source_cost: Decimal | None = None
    currency: str | None = None
    notes: str | None = None


@dataclass(slots=True)
class ParseResult:
    items: list[ParsedCode] = field(default_factory=list)
    skipped_blank: int = 0
    duplicates: int = 0
    errors: list[str] = field(default_factory=list)


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _cost(value: str | None) -> Decimal | None:
    cleaned = _clean(value)
    if cleaned is None:
        return None
    try:
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None


def parse_inventory(content: str, fmt: str) -> ParseResult:
    """Parse ``content`` (TXT or CSV) into a :class:`ParseResult`."""
    normalized = (fmt or "").strip().lower()
    if normalized not in SUPPORTED_FORMATS:
        raise ValueError(
            f"Unsupported inventory format '{fmt}'. Supported: "
            f"{', '.join(SUPPORTED_FORMATS)}."
        )
    if normalized == "txt":
        return _parse_txt(content)
    return _parse_csv(content)


def _parse_txt(content: str) -> ParseResult:
    result = ParseResult()
    seen: set[str] = set()
    for line in content.splitlines():
        code = line.strip()
        if not code:
            result.skipped_blank += 1
            continue
        if code in seen:
            result.duplicates += 1
            continue
        seen.add(code)
        result.items.append(ParsedCode(code=code))
    return result


def _parse_csv(content: str) -> ParseResult:
    result = ParseResult()
    reader = csv.DictReader(io.StringIO(content))
    fieldnames = [f.strip().lower() for f in (reader.fieldnames or [])]
    if "code" not in fieldnames:
        raise ValueError("CSV must have a 'code' column.")

    seen: set[str] = set()
    for row in reader:
        normalized = {(k or "").strip().lower(): v for k, v in row.items()}
        code = _clean(normalized.get("code"))
        if code is None:
            result.skipped_blank += 1
            continue
        if code in seen:
            result.duplicates += 1
            continue
        seen.add(code)
        result.items.append(
            ParsedCode(
                code=code,
                region=_clean(normalized.get("region")),
                platform=_clean(normalized.get("platform")),
                source_cost=_cost(normalized.get("source_cost")),
                currency=_clean(normalized.get("currency")),
                notes=_clean(normalized.get("notes")),
            )
        )
    return result
