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

import re
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup

from scrapers.tools.content_queries import build_card_fields
from scrapers.tools.data_card import format_data_row_html, render_f8_card_html
from scrapers.tools.data_row import format_data_row

# /designer reference frames (private .claude repo) — present locally, absent in
# CI without .claude. The template drift-guard skips cleanly when absent.
_DESIGNER_DIR = (
    Path(__file__).resolve().parents[2]
    / ".claude" / "plans" / "tickets" / "CTK-164" / "designs" / "round-1"
)
_TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "tools" / "card_templates"

# (public template, /designer reference frame) pairs — same byte-structure skeleton.
_TEMPLATE_PAIRS = [
    ("reel-frame-f7-arrivals-cover.html", "reel-frame-f7-arrivals-cover.html"),
    ("reel-frame-f7-arrivals.html", "reel-frame-f7-arrivals.html"),
    ("reel-frame-f8-superlative.html", "reel-frame-f8-superlative.html"),
    ("reel-frame-f9-lineage-cover.html", "reel-frame-f9-lineage-cover.html"),
    ("reel-frame-f9-lineage.html", "reel-frame-f9-lineage.html"),
]

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


# --- INV-01 parity across the D-4 Lineage degrade cases ---------------------
# build_card_fields decides which fields exist (degrade is upstream of
# format_data_row); the adapter must render whatever survives with parity.


def test_parity_lineage_year_missing():
    # v1 default: origin present, year absent -> Lineage. renders origin-only.
    fields = build_card_fields(
        price_value={"kind": "price-drop-new", "oldValue": "$650.00", "newValue": "$455.00"},
        origin="WWC", year=None, listed_at="2026-06-16T12:00:00Z",
    )
    assert [f["label"] for f in fields] == ["Price", "Lineage", "Listed"]
    _assert_parity(fields)
    assert format_data_row(fields, NOW) == "Price. $650.00 $455.00 — Lineage. WWC — Listed. 6 hours ago"


def test_parity_lineage_origin_missing():
    # Origin absent, year present -> Lineage. renders year-only.
    fields = build_card_fields(price_value="$250.00", origin=None, year=2018,
                               listed_at="2026-06-16T12:00:00Z")
    assert [f["label"] for f in fields] == ["Price", "Lineage", "Listed"]
    assert fields[1]["value"] == "2018"
    _assert_parity(fields)


def test_parity_lineage_both_absent_field_suppressed():
    # Both absent -> Lineage. omitted; row is Price. — Listed. and parity still holds.
    fields = build_card_fields(price_value="$250.00", origin=None, year=None,
                               listed_at="2026-06-16T12:00:00Z")
    assert [f["label"] for f in fields] == ["Price", "Listed"]
    _assert_parity(fields)
    assert format_data_row(fields, NOW) == "Price. $250.00 — Listed. 6 hours ago"


# --- template drift-guard: public card_templates skeleton == /designer frame -


# --- F7/F9 pure HTML builders (cover stat + inner lead + row) ---------------


def test_f7_cover_and_inner_builders():
    from scrapers.tools.data_card import (
        f7_cover_stat_html, render_cover_html, render_inner_html, _lead_html,
    )
    cover = render_cover_html("reel-frame-f7-arrivals-cover.html", f7_cover_stat_html(23))
    assert "{{" not in cover
    assert BeautifulSoup(cover, "html.parser").find("p", class_="stat").get_text() == "23 new arrivals this week."

    fields = build_card_fields(price_value="$250.00", origin="WWC", year=None,
                               listed_at="2026-06-16T12:00:00Z")
    inner = render_inner_html(
        "reel-frame-f7-arrivals.html",
        _lead_html("WWC Sunkist Bounce Mushroom", "WWC", "back in stock"),
        fields, NOW,
    )
    soup = BeautifulSoup(inner, "html.parser")
    assert soup.find("p", class_="lead").get_text() == "WWC Sunkist Bounce Mushroom back in stock at WWC."
    # Inner row still INV-01-parity-clean.
    assert soup.find("p", class_="row").get_text() == format_data_row(fields, NOW)


def test_f9_cover_prose_dash_and_listed_lead():
    from scrapers.tools.data_card import f9_cover_stat_html, render_cover_html, _lead_html
    cover = render_cover_html("reel-frame-f9-lineage-cover.html", f9_cover_stat_html("WWC Sunkist Bounce", 4))
    text = BeautifulSoup(cover, "html.parser").find("p", class_="stat").get_text()
    assert text == "WWC Sunkist Bounce — at 4 vendors right now."   # prose dash inside .stat
    # F9 inner lead uses 'listed at', and Listed. (not Back.) is the row's event field.
    assert _lead_html("WWC Sunkist Bounce Mushroom", "TSA", "listed") == (
        '<span class="name">WWC Sunkist Bounce Mushroom</span> listed at TSA.'
    )


def _style_block(html_text: str) -> str:
    m = re.search(r"<style>.*?</style>", html_text, re.S)
    assert m, "no <style> block found"
    return m.group(0)


def test_card_templates_skeleton_matches_designer_frames():
    """Pin the public card_templates' geometry/font skeleton (the <style> block) to
    /designer's reference frames byte-for-byte. The body differs (tokens vs
    placeholder content) — the data-row TEXT is INV-01-pinned separately — but a
    /designer geometry/font revision must force a template re-sync, not drift
    silently. Skips when .claude (the /designer source) isn't checked out (CI)."""
    import pytest
    if not _DESIGNER_DIR.is_dir():
        pytest.skip("/designer reference frames not present (.claude not checked out)")
    for template_name, frame_name in _TEMPLATE_PAIRS:
        public = (_TEMPLATE_DIR / template_name).read_text(encoding="utf-8")
        designer = (_DESIGNER_DIR / frame_name).read_text(encoding="utf-8")
        assert _style_block(public) == _style_block(designer), (
            f"{template_name} <style> drifted from /designer {frame_name} — re-sync the template"
        )


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
