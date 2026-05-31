"""scrapers/tests/test_diff_cohort_oos.py — CTK-094 §9 diff.classify cohort-OOS
+ restock-symmetry + no-regression tests.

Pure-function tests against in-memory fixtures (no DB, no network). Validates
the CTK-094 D-1 cohort-comparison-OOS pass in scrapers/common/diff.classify:

- §9.1/§9.2/§9.3 (POTO + AquaSD + TG cohort fixtures): with cohort_oos_at_persist
  True, URLs previously-in_stock that are absent from the current scrape's
  seen-set flip via synthetic ItemDecision(decision="oos", existing_id=...).
  Synthetic item carries minimal shape (product_url, in_stock=False,
  current_price=last_known) so persist_phase_a's absent-column = keep-existing
  contract preserves raw_title / normalized_title / etc.
- §9.2 restock-symmetry: a cohort-OOS row that reappears in the next scrape
  (in_stock=True) flips back via the existing per-item "restocked" branch.
- §9.4 no-regression: with cohort_oos_at_persist=False (default), the second
  tuple element is empty and the first element matches the pre-CTK-094 single-
  list return.
- §9.5 short-circuit: classify always emits cohort decisions when opt-in fires
  (gating happens at run.py per §3 short-circuit); test the tuple shape so the
  caller can discard the second list cleanly.

Runnable as:
  python -m scrapers.tests.test_diff_cohort_oos
"""

from __future__ import annotations

import sys
import traceback
from decimal import Decimal

from scrapers.common.diff import classify


# ---------------------------------------------------------------------------
# Fixture builders — minimal item / existing_by_url shapes that mirror what
# parse_shopify / parse_bigcommerce / tidal_gardens yield + db.fetch_existing
# returns. Each builder is a pure function; tests assemble them as needed.
# ---------------------------------------------------------------------------


def _make_item(product_url: str, in_stock: bool = True, current_price: str | None = "25.00") -> dict:
    """Real-parser item shape (parse_shopify._normalize_product post-CTK-094)."""
    return {
        "product_url": product_url,
        "raw_title": f"Title for {product_url}",
        "normalized_title": f"title for {product_url}",
        "current_price": Decimal(current_price) if current_price else None,
        "currency": "USD",
        "in_stock": in_stock,
        "category": "sps",
        "lineage_flag": "named",
        "vendor_sku": None,
        "vendor_image_url": None,
    }


def _make_existing(listing_id: int, product_url: str, in_stock: bool = True, current_price: str | None = "25.00") -> dict:
    """db.fetch_existing_listings row shape (SELECT id, product_url,
    current_price, in_stock, image_url FROM vendor_listings ...)."""
    return {
        "id": listing_id,
        "product_url": product_url,
        "current_price": Decimal(current_price) if current_price else None,
        "in_stock": in_stock,
        "image_url": None,
    }


# ---------------------------------------------------------------------------
# §9.1 POTO buyable-drop fixture
# ---------------------------------------------------------------------------


def test_poto_cohort_oos_flips_absent_in_stock():
    """5 URLs in DB in_stock=true; scrape sees 3. Expect 2 cohort-OOS decisions
    for the 2 absent URLs."""
    existing_by_url = {
        f"https://piecesoftheocean.com/products/coral-{i}": _make_existing(
            listing_id=i,
            product_url=f"https://piecesoftheocean.com/products/coral-{i}",
            in_stock=True,
            current_price="50.00",
        )
        for i in range(1, 6)
    }
    items = [
        _make_item(f"https://piecesoftheocean.com/products/coral-{i}", in_stock=True, current_price="50.00")
        for i in (1, 2, 3)
    ]

    per_item, cohort_oos = classify(items, existing_by_url, cohort_oos_at_persist=True)

    # Per-item: 3 unchanged (price/stock unchanged → unchanged decisions)
    assert len(per_item) == 3
    assert {d.decision for d in per_item} == {"unchanged"}

    # Cohort-OOS: 2 decisions for coral-4 + coral-5 (absent from scrape)
    assert len(cohort_oos) == 2
    cohort_urls = {d.item["product_url"] for d in cohort_oos}
    assert cohort_urls == {
        "https://piecesoftheocean.com/products/coral-4",
        "https://piecesoftheocean.com/products/coral-5",
    }
    for d in cohort_oos:
        assert d.decision == "oos"
        assert d.existing_id is not None
        assert d.item["in_stock"] is False
        # Last-known price preserved for price_history insert (existing row's
        # current_price flows through to the cohort item).
        assert d.item["current_price"] == Decimal("50.00")
        # Synthetic item omits raw_title — discriminator used by
        # persist_phase_a to build the minimal UPSERT payload.
        assert "raw_title" not in d.item


def test_poto_cohort_oos_skips_already_oos():
    """Existing OOS rows that stay absent should NOT re-emit OOS (idempotent
    on consecutive cohort passes — already-OOS rows don't generate noise)."""
    existing_by_url = {
        "https://piecesoftheocean.com/products/sold-already": _make_existing(
            listing_id=1, product_url="https://piecesoftheocean.com/products/sold-already",
            in_stock=False, current_price="50.00",
        ),
    }
    items: list[dict] = []  # nothing in scrape
    per_item, cohort_oos = classify(items, existing_by_url, cohort_oos_at_persist=True)
    assert per_item == []
    assert cohort_oos == []  # already OOS → no re-flip noise


# ---------------------------------------------------------------------------
# §9.2 Restock-symmetry cycle (cohort-OOS → reappear → restocked)
# ---------------------------------------------------------------------------


def test_restock_symmetry_after_cohort_oos():
    """Scrape #1: 5 URLs in_stock=true; scrape sees 3 → 2 flip OOS.
    Scrape #2: previously-OOS URL reappears in_stock=true → 'restocked' via
    the existing per-item branch."""
    # State after scrape #1: coral-4 + coral-5 flipped to in_stock=false
    existing_after_scrape_1 = {
        "https://piecesoftheocean.com/products/coral-1": _make_existing(1, "https://piecesoftheocean.com/products/coral-1", in_stock=True),
        "https://piecesoftheocean.com/products/coral-2": _make_existing(2, "https://piecesoftheocean.com/products/coral-2", in_stock=True),
        "https://piecesoftheocean.com/products/coral-3": _make_existing(3, "https://piecesoftheocean.com/products/coral-3", in_stock=True),
        "https://piecesoftheocean.com/products/coral-4": _make_existing(4, "https://piecesoftheocean.com/products/coral-4", in_stock=False),
        "https://piecesoftheocean.com/products/coral-5": _make_existing(5, "https://piecesoftheocean.com/products/coral-5", in_stock=False),
    }
    # Scrape #2: coral-4 reappears (POTO re-listed it), coral-5 stays absent
    items = [
        _make_item("https://piecesoftheocean.com/products/coral-1", in_stock=True),
        _make_item("https://piecesoftheocean.com/products/coral-2", in_stock=True),
        _make_item("https://piecesoftheocean.com/products/coral-3", in_stock=True),
        _make_item("https://piecesoftheocean.com/products/coral-4", in_stock=True),
    ]

    per_item, cohort_oos = classify(items, existing_after_scrape_1, cohort_oos_at_persist=True)

    # Per-item: 3 unchanged + 1 restocked (coral-4)
    decisions_by_url = {d.item["product_url"]: d for d in per_item}
    assert decisions_by_url["https://piecesoftheocean.com/products/coral-4"].decision == "restocked"
    assert decisions_by_url["https://piecesoftheocean.com/products/coral-1"].decision == "unchanged"

    # Cohort-OOS: 0 (coral-5 is already OOS in DB, no re-flip)
    assert cohort_oos == []


# ---------------------------------------------------------------------------
# §9.3 AquaSD overlap-dedup + cohort sees deduped seen-set
# ---------------------------------------------------------------------------


def test_aquasd_cohort_sees_deduped_seen_set():
    """Parser dedups overlap (/softies/ ∩ /zoanthids/ in parse_bigcommerce.
    fetch_and_parse end-of-function). diff.classify gets the deduped list,
    so a product present in both paths shows once in the seen-set; cohort
    pass does NOT falsely flip it."""
    overlap_url = "https://aquasd.com/products/rainbow-zoa/"
    existing_by_url = {
        overlap_url: _make_existing(1, overlap_url, in_stock=True),
        "https://aquasd.com/products/unique-softie/": _make_existing(2, "https://aquasd.com/products/unique-softie/", in_stock=True),
    }
    # Parser sends ONE entry per URL (post-dedup); the cohort pass sees the
    # overlap URL in the seen-set and does NOT flip it.
    items = [
        _make_item(overlap_url, in_stock=True),
        _make_item("https://aquasd.com/products/unique-softie/", in_stock=True),
    ]
    per_item, cohort_oos = classify(items, existing_by_url, cohort_oos_at_persist=True)
    assert cohort_oos == []  # overlap product correctly stays in_stock


def test_aquasd_cohort_flips_genuinely_absent():
    """8 URLs from /zoanthids/ in DB in_stock=true; scrape returns 6
    (Stencil silently OOS'd 2 of them). 2 cohort-OOS decisions."""
    existing_by_url = {
        f"https://aquasd.com/products/zoa-{i}/": _make_existing(
            listing_id=i, product_url=f"https://aquasd.com/products/zoa-{i}/", in_stock=True,
        )
        for i in range(1, 9)
    }
    items = [_make_item(f"https://aquasd.com/products/zoa-{i}/", in_stock=True) for i in range(1, 7)]
    per_item, cohort_oos = classify(items, existing_by_url, cohort_oos_at_persist=True)
    assert len(cohort_oos) == 2
    cohort_urls = {d.item["product_url"] for d in cohort_oos}
    assert cohort_urls == {
        "https://aquasd.com/products/zoa-7/",
        "https://aquasd.com/products/zoa-8/",
    }


# ---------------------------------------------------------------------------
# §9.3 Tidal Gardens paginated sold-out fixture
# ---------------------------------------------------------------------------


def test_tidal_gardens_cohort_oos_paginated_absent():
    """Scrape #1 found 30 URLs across 5 genus paths; scrape #2 finds 28
    (Magento hid 2 sold-out items pre-parser). 2 cohort-OOS decisions."""
    existing_by_url = {
        f"https://tidalgardens.com/products/tg-coral-{i}.html": _make_existing(
            listing_id=i,
            product_url=f"https://tidalgardens.com/products/tg-coral-{i}.html",
            in_stock=True,
        )
        for i in range(1, 31)
    }
    # Scrape #2 — 28 of 30 URLs return
    items = [
        _make_item(f"https://tidalgardens.com/products/tg-coral-{i}.html", in_stock=True)
        for i in range(1, 29)
    ]
    per_item, cohort_oos = classify(items, existing_by_url, cohort_oos_at_persist=True)
    assert len(cohort_oos) == 2
    assert {d.item["product_url"] for d in cohort_oos} == {
        "https://tidalgardens.com/products/tg-coral-29.html",
        "https://tidalgardens.com/products/tg-coral-30.html",
    }


# ---------------------------------------------------------------------------
# §9.4 No-regression: cohort_oos_at_persist=False → empty cohort list,
# per-item list byte-equivalent to pre-CTK-094 shape.
# ---------------------------------------------------------------------------


def test_no_regression_default_off_returns_empty_cohort():
    """8 stable-catalog vendors (PE/WWC/TSA/JF/BC/UC/Vivid/RC) default
    cohort_oos_at_persist=False. Cohort list MUST be empty even when
    existing rows would otherwise be absent-flipped — the absent-pass
    short-circuits entirely so byte-equivalence with pre-CTK-094 holds."""
    existing_by_url = {
        "https://pacificeastaquaculture.com/products/pe-coral-1": _make_existing(1, "https://pacificeastaquaculture.com/products/pe-coral-1", in_stock=True),
        "https://pacificeastaquaculture.com/products/pe-coral-2": _make_existing(2, "https://pacificeastaquaculture.com/products/pe-coral-2", in_stock=True),
    }
    items = [_make_item("https://pacificeastaquaculture.com/products/pe-coral-1", in_stock=True)]
    # pe-coral-2 absent from scrape, but cohort_oos_at_persist=False (default) → no flip.
    per_item, cohort_oos = classify(items, existing_by_url)  # default kwarg
    assert len(per_item) == 1
    assert per_item[0].decision == "unchanged"
    assert cohort_oos == []


def test_no_regression_per_item_decisions_match_pre_ctk094_shape():
    """Per-item decision sequence under cohort_oos_at_persist=False matches
    the pre-CTK-094 single-list return — covers new / price_changed /
    restocked / oos / unchanged."""
    existing_by_url = {
        "url-new": None,  # placeholder; real "new" decision means URL not in existing_by_url
        "url-price-changed": _make_existing(1, "url-price-changed", in_stock=True, current_price="10.00"),
        "url-restocked": _make_existing(2, "url-restocked", in_stock=False, current_price="20.00"),
        "url-going-oos": _make_existing(3, "url-going-oos", in_stock=True, current_price="30.00"),
        "url-unchanged": _make_existing(4, "url-unchanged", in_stock=True, current_price="40.00"),
    }
    # Strip the "url-new" placeholder — it's the absence-case
    existing_by_url.pop("url-new")

    items = [
        _make_item("url-new", in_stock=True, current_price="100.00"),
        _make_item("url-price-changed", in_stock=True, current_price="15.00"),
        _make_item("url-restocked", in_stock=True, current_price="20.00"),
        _make_item("url-going-oos", in_stock=False, current_price="30.00"),
        _make_item("url-unchanged", in_stock=True, current_price="40.00"),
    ]

    per_item, cohort_oos = classify(items, existing_by_url)
    decisions_by_url = {d.item["product_url"]: d.decision for d in per_item}

    assert decisions_by_url == {
        "url-new": "new",
        "url-price-changed": "price_changed",
        "url-restocked": "restocked",
        "url-going-oos": "oos",
        "url-unchanged": "unchanged",
    }
    assert cohort_oos == []


# ---------------------------------------------------------------------------
# §9.5 Short-circuit shape — classify always emits cohort decisions on opt-in;
# the caller (run.py) gates them on canary outcome. Test that the tuple shape
# allows the caller to discard the second list cleanly.
# ---------------------------------------------------------------------------


def test_classify_tuple_shape_supports_caller_gate():
    """classify returns a tuple even when cohort_oos_at_persist=False — the
    second element is just an empty list. Caller's gate logic ('if cohort_safe
    and cohort_oos_decisions: decisions = per_item + cohort_oos else: decisions
    = per_item') reads consistently across opt-in and opt-out."""
    existing_by_url = {
        "url-a": _make_existing(1, "url-a", in_stock=True),
        "url-b": _make_existing(2, "url-b", in_stock=True),
    }
    items = [_make_item("url-a", in_stock=True)]  # url-b absent

    # opt-out
    per_item_off, cohort_off = classify(items, existing_by_url, cohort_oos_at_persist=False)
    assert isinstance(per_item_off, list)
    assert isinstance(cohort_off, list)
    assert cohort_off == []

    # opt-in
    per_item_on, cohort_on = classify(items, existing_by_url, cohort_oos_at_persist=True)
    assert isinstance(per_item_on, list)
    assert isinstance(cohort_on, list)
    assert len(cohort_on) == 1
    assert cohort_on[0].item["product_url"] == "url-b"


def test_classify_single_pass_over_items_no_double_consume():
    """`items` iterable is consumed exactly once — the cohort-pass uses the
    seen_urls set built DURING the per-item loop, not a re-iteration. Catches
    the directive's must-not bug: 'do NOT call set(items) twice' — a
    generator passed twice would be empty on the second pass and mass-fire
    every existing in-stock row as cohort-OOS."""
    existing_by_url = {
        f"url-{i}": _make_existing(i, f"url-{i}", in_stock=True) for i in range(1, 4)
    }

    def items_generator():
        for i in (1, 2):
            yield _make_item(f"url-{i}", in_stock=True)

    # Pass the generator (single-shot iterable). If classify re-iterates,
    # the second pass would see zero items + flip all 3 existing in-stock
    # rows to cohort-OOS — test must catch that.
    per_item, cohort_oos = classify(items_generator(), existing_by_url, cohort_oos_at_persist=True)
    assert len(per_item) == 2  # generator consumed once
    assert len(cohort_oos) == 1  # only url-3 absent from seen_urls
    assert cohort_oos[0].item["product_url"] == "url-3"


# ---------------------------------------------------------------------------
# Main — runnable as `python -m scrapers.tests.test_diff_cohort_oos`
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    tests = [
        test_poto_cohort_oos_flips_absent_in_stock,
        test_poto_cohort_oos_skips_already_oos,
        test_restock_symmetry_after_cohort_oos,
        test_aquasd_cohort_sees_deduped_seen_set,
        test_aquasd_cohort_flips_genuinely_absent,
        test_tidal_gardens_cohort_oos_paginated_absent,
        test_no_regression_default_off_returns_empty_cohort,
        test_no_regression_per_item_decisions_match_pre_ctk094_shape,
        test_classify_tuple_shape_supports_caller_gate,
        test_classify_single_pass_over_items_no_double_consume,
    ]
    failures = []
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception:  # noqa: BLE001
            failures.append(t.__name__)
            print(f"FAIL {t.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - len(failures)}/{len(tests)} tests passed")
    sys.exit(1 if failures else 0)
