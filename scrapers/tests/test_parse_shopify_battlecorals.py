"""scrapers/tests/test_parse_shopify_battlecorals.py — CTK-096 title_denylist
axis, Battlecorals coverage.

Parse-only — no DB, no network. Pins drop-vs-keep behavior per BC YAML
title_denylist entry against synthetic products matching the 2026-05-31
empirical leak surface — Tee Shirt / Shirt non-Tee / Print / Gift Card /
delivery fee / shipping classes — plus FP-discipline controls on the
leading-space ` Print` substring (catches "X Print" merch but not
hypothetical "Imprint"/"Footprint" coral names) and the bare-word
`Shirt` superset semantic.

Runnable as:
  python -m scrapers.tests.test_parse_shopify_battlecorals
"""

from __future__ import annotations

import sys
import traceback

from scrapers.common.parse_shopify import _should_keep


# BC YAML shape at CTK-096 ship: large taxonomic product_type_allowlist (~70
# entries; we only use a subset relevant to test pivot — empty PT bucket where
# the merch leaks live, plus a coral PT for the keep cases). tag_denylist
# empty. title_denylist holds the 5 walk-grounded entries per CTK-096 D-1
# plus the 2 CTK-132 gag-listing exact-compounds (2026-06-07).
BC_FILTER = {
    "product_type_allowlist": [
        "", "Acropora", "Acropora sp.", "Acropora Tenuis", "Montipora",
    ],
    "tag_denylist": [],
    "title_denylist": [
        "delivery fee",
        "Gift Card",
        " Print",
        "shipping",
        "Shirt",
        "Fairy Food",
        "In a pigs eye",
    ],
}


def _p(title: str, product_type: str = "", tags=None) -> dict:
    return {"title": title, "product_type": product_type, "tags": tags or []}


# --- Drop: per-entry empirical class pin ---

def test_bc_drops_tee_shirt():
    """`Shirt` substring catches `Tee Shirt` superset (4 walk-rows)."""
    for title in [
        "Raindrops on Roses contest Tee Shirt",
        "I Heart BC Tee Shirt",
        "Battlebox Tee Shirt",
        "BC Tee Shirt",
    ]:
        assert _should_keep(_p(title), BC_FILTER) is False, title


def test_bc_drops_shirt_non_tee():
    """`Shirt` also catches the lone non-Tee variant."""
    assert _should_keep(_p("Superb Owl Shirt"), BC_FILTER) is False


def test_bc_drops_print_suffix_class():
    """Leading-space ` Print` substring catches the ~27 `X Print` rows from
    the 2026-05-31 live-walk surface + the Session 1 walk-confirm Δ (`4 pack
    of 20x20 prints` carries lowercase `prints`, caught case-insensitively)."""
    for title in [
        "Pink Polyp Table Print",
        "Battlejuice Print",
        "Hyperberry Print",
        "Bananaboy Blue Print",
        "Superb Owl Print",
        "4 pack of 20x20 prints",  # lowercase variant from Session 1 walk-confirm
    ]:
        assert _should_keep(_p(title), BC_FILTER) is False, title


def test_bc_drops_gift_card():
    """`Gift Card` substring catches the 'Gift Cards' promo row."""
    assert _should_keep(_p("Gift Cards"), BC_FILTER) is False


def test_bc_drops_delivery_fee():
    """`delivery fee` substring catches the Saturday delivery service row."""
    assert _should_keep(_p("Saturday delivery fee"), BC_FILTER) is False


def test_bc_drops_shipping():
    """`shipping` substring catches `UPS actual shipping` + the Session 1
    walk-confirm Δ (`shipping for Replacements`)."""
    for title in [
        "UPS actual shipping",
        "shipping for Replacements",
    ]:
        assert _should_keep(_p(title), BC_FILTER) is False, title


def test_bc_drops_gag_listings():
    """CTK-132 gag-listing class: both 2026-06-07 walk members drop. The
    pigs-eye entry omits the trailing `!` (substring catches the punctuated
    live title); Fairy Food drops even from its allowlisted coral PT bucket —
    title_denylist is AND-semantics, not PT-scoped."""
    assert _should_keep(_p("In a pigs eye!"), BC_FILTER) is False
    assert _should_keep(_p("Fairy Food", product_type="Acropora sp."), BC_FILTER) is False


# --- Keep: FP-discipline controls + baseline coral ---

def test_bc_keeps_hypothetical_imprint_coral():
    """Leading-space ` Print` requires whitespace before — hypothetical coral
    titled `BC Imprint Acropora` must NOT false-fire (substring `imprint`
    starts mid-word). Pins the FP-discipline reason for leading-space."""
    # Note: the synthetic title `BC Imprint Acropora` contains NO ` print`
    # substring (just `mprint`); `Imprint` starts with `I` at position 3.
    p = _p("BC Imprint Acropora", product_type="Acropora")
    assert _should_keep(p, BC_FILTER) is True


def test_bc_keeps_regular_acropora():
    """Sanity: a normal BC coral row stays kept."""
    p = _p("Hyperberry", product_type="Acropora sp.", tags=["acropora"])
    assert _should_keep(p, BC_FILTER) is True


def test_bc_keeps_empty_pt_real_coral():
    """Empty-PT bucket still passes when title has no denylist substring —
    Q-8 (a) BC precedent preserved (Battlebox grab-bags + house lineages in
    PT='' remain in the catalog)."""
    p = _p("Genie of Death", product_type="", tags=[])
    assert _should_keep(p, BC_FILTER) is True


def test_bc_keeps_fairy_compound_corals():
    """CTK-132 FP-discipline control: the gag entry is the full compound
    `Fairy Food` precisely because bare `Fairy` collides with ~50 real coral
    rows fleet-wide (Fairy Dust / Fairy Tales / Fairy Farts families per the
    2026-06-07 DB-wide ILIKE scan). Pins the reason the entry must never be
    shortened."""
    for title in [
        "Fairy Dust Favia",
        "JF Fairy Tale Zoanthids",
        "Fairy Farts",
    ]:
        p = _p(title, product_type="Acropora sp.")
        assert _should_keep(p, BC_FILTER) is True, title


def main() -> int:
    tests = [
        test_bc_drops_tee_shirt,
        test_bc_drops_shirt_non_tee,
        test_bc_drops_print_suffix_class,
        test_bc_drops_gift_card,
        test_bc_drops_delivery_fee,
        test_bc_drops_shipping,
        test_bc_drops_gag_listings,
        test_bc_keeps_hypothetical_imprint_coral,
        test_bc_keeps_regular_acropora,
        test_bc_keeps_empty_pt_real_coral,
        test_bc_keeps_fairy_compound_corals,
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
