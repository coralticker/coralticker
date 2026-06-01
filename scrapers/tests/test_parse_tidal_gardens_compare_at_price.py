"""scrapers/tests/test_parse_tidal_gardens_compare_at_price.py — CTK-100 Wave-2
Magento compare_at_price capture tests (Tidal Gardens).

Parse-only — no DB, no network. Five cases per directive + plan W2-§B:
  (a) present oldPrice with valid data-price-amount > finalPrice → captures
  (b) oldPrice element absent → None
  (c) oldPrice <= finalPrice → None (L2 stale)
  (d) (TG has no auction surface; the equivalent L4 case is current_price=None
      via price-on-request — covered explicitly)
  (e) billion-dollar typo data-price-amount='100000000.00' → None (F15 clamp)

Wave-2 audit (2026-06-01) found n=4 live marked-down listings across 3 distinct
genus subpaths; oldPrice > finalPrice direction holds. data-price-amount is a
clean integer/decimal string (no $ prefix, no commas) — matches the existing
_extract_price shape.

Runnable as:
  python -m scrapers.tests.test_parse_tidal_gardens_compare_at_price
"""

from __future__ import annotations

import sys
import traceback
from decimal import Decimal

from bs4 import BeautifulSoup

from scrapers.vendors.tidal_gardens import _extract_compare_at_price


def _card_with_oldprice(old_amount: str | None) -> BeautifulSoup:
    """Build a minimum Magento WeltPixel card with an optional oldPrice
    span. None = element absent (the dominant case — non-sale listing);
    "100" = populated oldPrice with data-price-amount integer/decimal."""
    if old_amount is None:
        html = '<li class="item product product-item"><span data-price-type="finalPrice" data-price-amount="80"></span></li>'
    else:
        html = (
            '<li class="item product product-item">'
            f'<span data-price-type="oldPrice" data-price-amount="{old_amount}"></span>'
            '<span data-price-type="finalPrice" data-price-amount="80"></span>'
            "</li>"
        )
    return BeautifulSoup(html, "html.parser").select_one("li")


# --- Cases a/b/c/e — unit tests ---

def test_a_oldprice_present_and_valid_captures():
    """(a) oldPrice data-price-amount=110, current_price=Decimal("85")
    (Beginner Coral Pack shape from the live audit) → captures
    Decimal('110')."""
    card = _card_with_oldprice("110")
    result = _extract_compare_at_price(card, "/corals/soft-corals.html", "Beginner Coral Pack", Decimal("85"))
    assert result == Decimal("110"), f"expected Decimal('110'); got {result!r}"


def test_a_audit_evidence_replay():
    """(a-replay) Replay the four live audit-evidence rows from the Wave-2
    Session 1 sweep — Beginner Coral Pack, Feeling Lucky 10/5, Leopard
    Discosoma. Pins direction (oldPrice > finalPrice) + amount-parse
    shape (clean integer string)."""
    audit_evidence = [
        ("Beginner Coral Pack", "110", "85"),
        ("Feeling Lucky Zoanthid 10 Pack", "360", "245"),
        ("Feeling Lucky Zoanthid 5 Pack", "170", "120"),
        ("Leopard Discosoma Mushroom", "55", "20"),
    ]
    for title, old_amt, final_amt in audit_evidence:
        card = _card_with_oldprice(old_amt)
        current = Decimal(final_amt)
        result = _extract_compare_at_price(card, "/corals/audit-replay.html", title, current)
        assert result == Decimal(old_amt), f"{title}: expected Decimal({old_amt!r}); got {result!r}"


def test_b_oldprice_absent_returns_none():
    """(b) Card without oldPrice element at all (the dominant case —
    non-sale TG listing) → None."""
    card = _card_with_oldprice(None)
    result = _extract_compare_at_price(card, "/corals/sps.html", "Non-sale Acro", Decimal("80"))
    assert result is None, f"expected None on absent oldPrice; got {result!r}"


def test_b_oldprice_empty_amount_returns_none():
    """(b-variant) oldPrice element present but data-price-amount is
    empty / missing → None. Magento template can render the span shell
    with no amount in certain edge states; guard returns None silently."""
    # Build a card with empty data-price-amount
    html = (
        '<li class="item product product-item">'
        '<span data-price-type="oldPrice" data-price-amount=""></span>'
        '<span data-price-type="finalPrice" data-price-amount="80"></span>'
        "</li>"
    )
    card = BeautifulSoup(html, "html.parser").select_one("li")
    result = _extract_compare_at_price(card, "/corals/sps.html", "Empty-amount Edge", Decimal("80"))
    assert result is None


def test_c_stale_oldprice_returns_none():
    """(c) oldPrice <= finalPrice → None (L2 stale). Three sub-cases:
    less / equal / zero. Same shape as Wave-1 Shopify + BC tests."""
    current = Decimal("80")
    for stale_amt in ("60", "80", "0"):
        card = _card_with_oldprice(stale_amt)
        result = _extract_compare_at_price(card, "/corals/sps.html", "Stale Test", current)
        assert result is None, f"stale value {stale_amt!r} should null; got {result!r}"


def test_l4_current_price_none_returns_none():
    """L4 — current_price is None (price-on-request; TG has no auction
    surface today but the guard is structural). Even with populated
    oldPrice, returns None."""
    card = _card_with_oldprice("100")
    result = _extract_compare_at_price(card, "/corals/sps.html", "L4 Test", current_price=None)
    assert result is None


def test_e_clamp_billion_dollar_typo_nulls():
    """(e) F15 — vendor typo data-price-amount='100000000' (1e8) →
    None. Magento data-price-amount is a clean numeric string; a typo
    here parses as a finite Decimal that would raise
    NumericValueOutOfRange at the numeric(10,2) UPSERT."""
    card = _card_with_oldprice("100000000")
    result = _extract_compare_at_price(card, "/corals/sps.html", "Typo Test", Decimal("80"))
    assert result is None, f"clamp should null at 1e8; got {result!r}"


def test_clamp_boundary_just_under_overflow_captures():
    """F15 boundary — '99999999.99' MUST capture, not null. Boundary
    pin against `>` vs. `>=` drift."""
    card = _card_with_oldprice("99999999.99")
    result = _extract_compare_at_price(card, "/corals/sps.html", "Boundary Test", Decimal("80"))
    assert result == Decimal("99999999.99"), f"boundary value must capture; got {result!r}"


def test_non_finite_oldprice_does_not_crash():
    """F2 (Wave-1.5 carried) — data-price-amount='NaN' / 'Infinity' →
    None silently via is_finite()."""
    for bad in ("NaN", "Infinity", "-Infinity"):
        card = _card_with_oldprice(bad)
        result = _extract_compare_at_price(card, "/corals/sps.html", "Non-finite Test", Decimal("80"))
        assert result is None, f"data-price-amount={bad!r} should null; got {result!r}"


def main() -> int:
    tests = [
        test_a_oldprice_present_and_valid_captures,
        test_a_audit_evidence_replay,
        test_b_oldprice_absent_returns_none,
        test_b_oldprice_empty_amount_returns_none,
        test_c_stale_oldprice_returns_none,
        test_l4_current_price_none_returns_none,
        test_e_clamp_billion_dollar_typo_nulls,
        test_clamp_boundary_just_under_overflow_captures,
        test_non_finite_oldprice_does_not_crash,
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
    total = len(tests)
    print(f"\n{total - failed}/{total} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
