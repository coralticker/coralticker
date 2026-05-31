"""scrapers/tests/test_parse_shopify_jf.py — CTK-096 title_denylist axis,
JF coverage.

Parse-only — no DB, no network. Pins drop-vs-keep behavior per JF YAML
title_denylist entry against synthetic products matching the 2026-05-31
empirical leak surface + the false-positive coral neighbors that pinned
the compound-substring discipline (single-word `Tang` would mis-fire on
Tangerine/Tango/Tangelo coral; the chosen `Hybrid Tang` does not).

Runnable as:
  python -m scrapers.tests.test_parse_shopify_jf
"""

from __future__ import annotations

import sys
import traceback

from scrapers.common.parse_shopify import _should_keep


# JF YAML shape at CTK-096 ship: product_type_allowlist covers WYSIWYG / SPS /
# LPS / Zoanthids/Softies / Chalices / MYSTERY BOX / "". tag_denylist empty.
# title_denylist holds the single compound entry per CTK-096 D-1 + D-3
# walk-confirm.
JF_FILTER = {
    "product_type_allowlist": [
        "", "Chalices", "LPS", "MYSTERY BOX", "SPS", "WYSIWYG", "Zoanthids/Softies",
    ],
    "tag_denylist": [],
    "title_denylist": ["Hybrid Tang"],
}


def _p(title: str, product_type: str = "WYSIWYG", tags=None) -> dict:
    """Synthetic Shopify product minimal-shape for _should_keep tests."""
    return {"title": title, "product_type": product_type, "tags": tags or []}


# --- Drop: empirical Hybrid Tang leak (2026-05-31 live-walk surface) ---

def test_jf_drops_hybrid_tang_caps():
    """The single 2026-05-31 walk-surface row: ALL-CAPS title, WYSIWYG PT,
    WYSIWYG tag. Pre-CTK-096 this passed every axis (PT in allowlist, tags not
    in empty denylist). With title_denylist: Hybrid Tang substring catches."""
    p = _p("WHITE AND YELLOW LIP HYBRID TANG (LOCAL PICK UP ONLY IN MARYLAND)",
           product_type="WYSIWYG", tags=["WYSIWYG"])
    assert _should_keep(p, JF_FILTER) is False


def test_jf_drops_hybrid_tang_lowercase():
    """Case-insensitive per CTK-096 D-1 — same row in hypothetical lowercase
    spelling (defensive against a vendor title-case change)."""
    p = _p("white and yellow lip hybrid tang", product_type="WYSIWYG", tags=[])
    assert _should_keep(p, JF_FILTER) is False


# --- Keep: false-positive coral neighbors (single-word 'Tang' would mis-fire) ---

def test_jf_keeps_tangerine_twisters_cloves():
    """JF coral lineage. Single-word `Tang` would catch; compound `Hybrid Tang`
    is FP-clean. This is the load-bearing FP discipline pin per CTK-096 D-1
    risk-and-discipline note (feedback_rotating_bucket_allowlist.md sibling)."""
    p = _p("JF TANGERINE TWISTERS CLOVES",
           product_type="Zoanthids/Softies", tags=[])
    assert _should_keep(p, JF_FILTER) is True


def test_jf_keeps_wwc_mango_tango_acan():
    """Cross-vendor WWC lineage at JF carrying `Tango` token. Single-word
    `Tang` substring would false-fire (`tang` ⊂ `tango`); compound is clean."""
    p = _p("WWC MANGO TANGO ACAN ECHINATA", product_type="LPS", tags=[])
    assert _should_keep(p, JF_FILTER) is True


def test_jf_keeps_jason_fox_tangelo_psammocora():
    """JF longform coral title carrying `Tangelo` token. Same FP class."""
    p = _p("JASON FOX TANGELO PSAMMOCORA", product_type="SPS", tags=[])
    assert _should_keep(p, JF_FILTER) is True


# --- Keep: baseline coral row (no title_denylist match) ---

def test_jf_keeps_regular_coral():
    """Sanity: a normal JF WYSIWYG coral row stays kept."""
    p = _p("JF SUNTAN DIGI", product_type="WYSIWYG", tags=["WYSIWYG"])
    assert _should_keep(p, JF_FILTER) is True


def main() -> int:
    tests = [
        test_jf_drops_hybrid_tang_caps,
        test_jf_drops_hybrid_tang_lowercase,
        test_jf_keeps_tangerine_twisters_cloves,
        test_jf_keeps_wwc_mango_tango_acan,
        test_jf_keeps_jason_fox_tangelo_psammocora,
        test_jf_keeps_regular_coral,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {t.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
