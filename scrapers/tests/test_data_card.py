"""CTK-164 B-path — INV-01 parity for the data-card data-row adapter (the PB-3
gate) + F8 card assembly.

The crux: data_card.format_data_row_html (card HTML) and data_row.format_data_row
(flat text) render the SAME `fields` list two ways. INV-01 binds them to one
shape; this test strips the card row HTML back to text (BeautifulSoup.get_text,
which unescapes entities) and asserts byte-equality with format_data_row. A drift
in either renderer — a reordered field, a dropped separator, a wrong value-kind
branch — fails here. Pure: no DB, no browser.

  python -m pytest scrapers/tests/test_data_card.py
"""

from __future__ import annotations

from datetime import datetime, timezone

from bs4 import BeautifulSoup

from scrapers.tools.data_card import format_data_row_html, render_f8_card_html
from scrapers.tools.data_row import format_data_row

# Fixed clock so the relative-time field is deterministic.
NOW = datetime(2026, 6, 16, 18, 0, 0, tzinfo=timezone.utc)


def _strip(html_fragment: str) -> str:
    return BeautifulSoup(html_fragment, "html.parser").get_text()


def _assert_parity(fields):
    assert _strip(format_data_row_html(fields, NOW)) == format_data_row(fields, NOW)


def test_parity_f8_price_drop_row():
    # The F8 superlative row: a price drop, lineage, a relative listed-time.
    fields = [
        {"label": "Price", "value": {"kind": "price-drop-new", "oldValue": "$650", "newValue": "$455"}},
        {"label": "Lineage", "value": "WWC · 2018"},
        {"label": "Listed", "value": {"kind": "relative-time", "timestamp": "2026-06-16T12:00:00Z"}},
    ]
    _assert_parity(fields)
    # Spot-check the literal canonical text too (catches a both-renderers-agree-but-
    # both-wrong drift the round-trip alone wouldn't).
    assert format_data_row(fields, NOW) == "Price. $650 $455 — Lineage. WWC · 2018 — Listed. 6 hours ago"


def test_parity_bare_and_relative():
    fields = [
        {"label": "Vendor", "value": "World Wide Corals"},
        {"label": "Listed", "value": {"kind": "relative-time", "timestamp": "2026-06-16T17:30:00Z"}},
    ]
    _assert_parity(fields)


def test_parity_vendor_markdown():
    fields = [
        {"label": "Price", "value": {"kind": "vendor-markdown", "oldValue": "$120", "newValue": "$90"}},
    ]
    _assert_parity(fields)


def test_parity_invalidated_and_italic():
    fields = [
        {"label": "Was", "value": {"kind": "invalidated", "value": "$300"}},
        {"label": "Note", "value": {"kind": "italic", "value": "price on request"}},
    ]
    _assert_parity(fields)


def test_parity_entity_safe_value():
    # A value with an HTML-significant char must survive escape -> strip round-trip.
    fields = [{"label": "Coral", "value": "Tom & Jerry Acro <rare>"}]
    _assert_parity(fields)


def test_unknown_kind_raises():
    import pytest
    with pytest.raises(ValueError):
        format_data_row_html([{"label": "X", "value": {"kind": "bogus"}}], NOW)


def test_f8_card_html_injects_and_keeps_row_parity():
    fields = [
        {"label": "Price", "value": {"kind": "price-drop-new", "oldValue": "$650", "newValue": "$455"}},
        {"label": "Lineage", "value": "WWC · 2018"},
        {"label": "Listed", "value": {"kind": "relative-time", "timestamp": "2026-06-16T12:00:00Z"}},
    ]
    card = render_f8_card_html(name="WWC Sunkist Bounce Mushroom", pct=30, fields=fields, now=NOW)

    # All tokens replaced.
    assert "{{" not in card and "}}" not in card
    assert "WWC Sunkist Bounce Mushroom" in card
    assert ">30%<" in card

    # The .row content, extracted from the full card, still strips to the canonical row.
    soup = BeautifulSoup(card, "html.parser")
    row = soup.find("p", class_="row")
    assert row is not None
    assert row.get_text() == format_data_row(fields, NOW)


def _run_all() -> int:
    import sys
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failures = 0
    for fn in fns:
        try:
            fn()
            print(f"ok   {fn.__name__}")
        except Exception as e:  # noqa: BLE001
            failures += 1
            print(f"FAIL {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(fns) - failures}/{len(fns)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    import sys
    sys.exit(_run_all())
