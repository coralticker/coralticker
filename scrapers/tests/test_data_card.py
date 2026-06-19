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
    # v1 D-4 two-field superlative row: Price. (drop pair) — Listed. (Lineage dropped).
    fields = [
        {"label": "Price", "value": {"kind": "price-drop-new", "oldValue": "$650", "newValue": "$455"}},
        {"label": "Listed", "value": {"kind": "relative-time", "timestamp": "2026-06-16T12:00:00Z"}},
    ]
    _assert_parity(fields)
    # Spot-check the literal canonical text too (catches a both-renderers-agree-but-
    # both-wrong drift the round-trip alone wouldn't).
    assert format_data_row(fields, NOW) == "Price. $650 $455 — Listed. 6 hours ago"
    # The struck-old / forest-new markup the .row CSS expects.
    assert '<span class="struck">$650</span> <span class="new">$455</span>' in format_data_row_html(fields, NOW)


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


def test_parity_italic():
    # Italic = the scientific-binomial carve-out (.row em). Latent in v1 but the
    # adapter path is kept; parity + the <em> markup must hold.
    fields = [{"label": "Note", "value": {"kind": "italic", "value": "Acropora"}}]
    _assert_parity(fields)
    assert "<em>Acropora</em>" in format_data_row_html(fields, NOW)


def test_invalidated_kind_is_card_forbidden():
    # B-path posts ACTIVE listings only; .row .invalid is absent from the frames.
    # An invalidated value reaching a card must fail loud, not silently render.
    import pytest
    with pytest.raises(ValueError):
        format_data_row_html([{"label": "Was", "value": {"kind": "invalidated", "value": "$300"}}], NOW)


def test_parity_entity_safe_value():
    # A value with an HTML-significant char must survive escape -> strip round-trip.
    fields = [{"label": "Coral", "value": "Tom & Jerry Acro <rare>"}]
    _assert_parity(fields)


def test_unknown_kind_raises():
    import pytest
    with pytest.raises(ValueError):
        format_data_row_html([{"label": "X", "value": {"kind": "bogus"}}], NOW)


# --- INV-01 parity over the v1 two-field row (built via build_card_fields) ---


def test_parity_two_field_row():
    # build_card_fields yields exactly Price. — Listed. in v1 (Lineage dropped),
    # regardless of origin/year; the adapter renders it with parity.
    fields = build_card_fields(
        price_value={"kind": "price-drop-new", "oldValue": "$650.00", "newValue": "$455.00"},
        origin="WWC", year=None, listed_at="2026-06-16T12:00:00Z",
    )
    assert [f["label"] for f in fields] == ["Price", "Listed"]
    _assert_parity(fields)
    assert format_data_row(fields, NOW) == "Price. $650.00 $455.00 — Listed. 6 hours ago"


# --- template drift-guard: public card_templates skeleton == /designer frame -


# --- F7/F9 pure HTML builders (cover stat + inner lead + row) ---------------


def test_f7_cover_and_inner_builders():
    from scrapers.tools.data_card import (
        f7_cover_stat_html, render_cover_html, render_inner_html, _lead_html,
    )
    cover = render_cover_html("reel-frame-f7-arrivals-cover.html", f7_cover_stat_html(23, "all-arrivals"))
    assert "{{" not in cover
    assert BeautifulSoup(cover, "html.parser").find("p", class_="stat").get_text() == "23 new arrivals this week."
    # Cover copy is composition-picked per the register lock (rev2 L177-179);
    # the count rides a .num span, so the strip yields "{N} {copy}".
    def _stat_text(n, comp):
        return BeautifulSoup(
            render_cover_html("reel-frame-f7-arrivals-cover.html", f7_cover_stat_html(n, comp)),
            "html.parser",
        ).find("p", class_="stat").get_text()
    assert _stat_text(5, "all-restocks") == "5 back in stock this week."
    assert _stat_text(47, "mixed") == "47 drops this week."

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
    assert text == "WWC Sunkist Bounce — carried at 4 vendors right now."   # prose dash inside .stat; "carried at" = stock claim not buy claim (CTK-161 retro #4)
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


def test_f8_reveal_card_keeps_row_parity_by_construction():
    # The reveal/strike-draw card injects the SAME format_data_row_html output as the
    # static F8, so its .row strips to format_data_row byte-for-byte — the animation
    # is a presentation layer over the parity-pinned row, never a re-format. (The
    # held-frame DOM textContent is asserted live in test_rasterize.)
    from scrapers.tools.data_card import build_f8_reveal
    fields = [
        {"label": "Price", "value": {"kind": "price-drop-new", "oldValue": "$650.00", "newValue": "$455.00"}},
        {"label": "Listed", "value": {"kind": "relative-time", "timestamp": "2026-06-15T18:00:00Z"}},
    ]
    html_doc, total = build_f8_reveal(name="WWC Sunkist Bounce Mushroom", pct=30, fields=fields, now=NOW)
    assert "{{" not in html_doc and "}}" not in html_doc
    assert total > 0
    soup = BeautifulSoup(html_doc, "html.parser")
    row = soup.find("p", class_="row")
    assert row is not None and row.get_text() == format_data_row(fields, NOW)
    # No -> arrow, no trailing period baked into the row text.
    assert "→" not in row.get_text() and not row.get_text().endswith(".")


def test_inner_reveal_card_keeps_row_parity_by_construction():
    # CTK-173: the F7/F9 inner plain-reveal card injects the SAME format_data_row_html
    # output as the static inner, so its .row strips to format_data_row byte-for-byte —
    # the reveal is a presentation layer over the parity-pinned row, never a re-format.
    # (The held-frame DOM textContent is asserted live in test_rasterize.)
    from scrapers.tools.data_card import build_inner_reveal, _lead_html
    fields = build_card_fields(price_value="$250.00", origin="WWC", year=None,
                               listed_at="2026-06-16T12:00:00Z")
    html_doc, total = build_inner_reveal(
        lead_html=_lead_html("WWC Sunkist Bounce Mushroom", "TSA", "back in stock"),
        fields=fields, now=NOW,
    )
    assert "{{" not in html_doc and "}}" not in html_doc
    assert total > 0
    soup = BeautifulSoup(html_doc, "html.parser")
    lead = soup.find("p", class_="lead")
    assert lead is not None and lead.get_text() == "WWC Sunkist Bounce Mushroom back in stock at TSA."
    row = soup.find("p", class_="row")
    assert row is not None and row.get_text() == format_data_row(fields, NOW)


def test_f9_cover_reveal_keeps_locked_prose_by_construction():
    # CTK-173: the F9 cover plain-staged-reveal injects the SAME f9_cover_stat_html
    # output (the locked 'carried at N' prose in presentation-only .seg spans), so the
    # held frame strips to the byte-identical locked cover string — opacity-only stage.
    from scrapers.tools.data_card import build_f9_cover_reveal, f9_cover_stat_html
    html_doc, total = build_f9_cover_reveal(coral="WWC Sunkist Bounce", vendor_count=4)
    assert "{{" not in html_doc and "}}" not in html_doc
    assert total > 0
    soup = BeautifulSoup(html_doc, "html.parser")
    stat = soup.find("p", class_="stat")
    assert stat is not None
    # get_text is byte-identical to the static cover string (the .seg wrappers strip away).
    assert stat.get_text() == "WWC Sunkist Bounce — carried at 4 vendors right now."
    assert BeautifulSoup(f9_cover_stat_html("WWC Sunkist Bounce", 4), "html.parser").get_text() == stat.get_text()
    # Three stage segments are present for the reveal to drive.
    assert all(stat.find("span", class_=f"seg{n}") is not None for n in (1, 2, 3))


def test_count_up_values_guarantees():
    # The count-up value sequence is pure + seek-driven: frame 0 == 0, terminal ==
    # exactly N (round, not floor), monotonic non-decreasing, length == build + hold.
    from scrapers.tools.data_card import count_up_values, COUNT_UP_BUILD_SEC, COUNT_UP_HOLD_SEC
    fps = 30
    build = max(1, round(COUNT_UP_BUILD_SEC * fps))
    expected_len = build + max(1, round(COUNT_UP_HOLD_SEC * fps))
    for n in (0, 1, 716, 1000):
        vals = count_up_values(n, fps=fps)
        assert vals[0] == 0, n
        assert vals[-1] == n, n                                # exact terminal, never floored short
        assert len(vals) == expected_len, n
        assert all(b >= a for a, b in zip(vals, vals[1:])), n   # monotonic non-decreasing
        assert max(vals) == n                                  # never overshoots N
    # Ease-out quad over the full build: the climb DECELERATES continuously — fast
    # start, gentle landing (what reads as "slowing the whole way" vs a flat ramp).
    # Per-frame steps trend down; allow +1 frame-to-frame integer-rounding noise, and
    # assert the early third is clearly faster than the late third.
    vals = count_up_values(716, fps=fps)
    steps = [vals[i + 1] - vals[i] for i in range(build - 1)]
    assert all(steps[i] >= steps[i + 1] - 1 for i in range(len(steps) - 1)), "climb has a real speed-up"
    third = max(1, len(steps) // 3)
    assert sum(steps[:third]) > 2 * sum(steps[-third:]), "climb does not clearly decelerate early->late"


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
