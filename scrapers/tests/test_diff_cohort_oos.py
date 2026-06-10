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

CTK-106 admitted-set contract (decision #83) — verify-pass tests 1-6: the
CTK-094 fold-#4 filtered-URL exclusion is retired. `in_stock=true` is asserted
only while a row is in the vendor's current admitted set (parsed + YAML-filter-
passed); filter-rejected rows flip OOS through the cohort pass for either
cause (vendor-recat or operator-tighten). `filtered_urls` is observability-
only. The vendor-recat flip test REPLACES the original exclusion regression
test — the expectation inverted at the contract change.

Runnable as:
  python -m scrapers.tests.test_diff_cohort_oos
"""

from __future__ import annotations

import sys
import traceback
from decimal import Decimal

from scrapers.common.diff import Counters, ItemDecision, classify
from scrapers.common.run import _apply_cohort_gate, _flip_cap_tripped, _resolve_flip_cap


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


# ---------------------------------------------------------------------------
# CTK-106 admitted-set contract (decision #83) — verify-pass tests 1-6.
# The fold-#4 exclusion regression test that lived here
# (test_filtered_urls_excluded_from_cohort_absent_set) is REPLACED by
# test_vendor_recat_filtered_url_flips below: the expectation inverted at
# the contract change (vendor-recat rows now flip, deliberately).
# ---------------------------------------------------------------------------


def test_operator_tighten_filtered_url_flips():
    """CTK-106 verify-pass 1 — operator-tighten: a previously-admitted
    in-stock row, still present in the vendor feed but newly denied by a
    YAML filter edit (tag_denylist / product_type_allowlist tightening),
    joins the cohort absent-set and flips OOS. This is the CTK-104 6-fish /
    CTK-119 / CTK-121 hand-bridge class — under the retired fold-#4
    exclusion these rows persisted as stale in_stock=true."""
    existing_by_url = {
        "url-still-admitted": _make_existing(1, "url-still-admitted", in_stock=True),
        "url-newly-denied": _make_existing(2, "url-newly-denied", in_stock=True, current_price="80.00"),
    }
    # The newly-denied row is in the FEED but the parser rejected it, so it
    # reaches classify via filtered_urls, not items.
    items = [_make_item("url-still-admitted", in_stock=True)]
    per_item, cohort_oos = classify(
        items,
        existing_by_url,
        cohort_oos_at_persist=True,
        filtered_urls={"url-newly-denied"},
    )
    assert len(cohort_oos) == 1
    d = cohort_oos[0]
    assert d.item["product_url"] == "url-newly-denied"
    assert d.decision == "oos"
    assert d.existing_id == 2
    assert d.item["in_stock"] is False
    # Last-known price rides into price_history alongside the flip.
    assert d.item["current_price"] == Decimal("80.00")


def test_vendor_recat_filtered_url_flips():
    """CTK-106 verify-pass 2 — vendor-recat: vendor moves a tracked item to
    a non-allowlisted product_type; the parser rejects it; it exits the
    admitted set and flips OOS. REPLACES the original fold-#4 no-flip
    expectation: still-live-but-untracked must not render as available at a
    stale price (D-1; the WWC Auction 5 are the worked example)."""
    existing_by_url = {
        "url-still-in-scrape": _make_existing(1, "url-still-in-scrape", in_stock=True),
        "url-vendor-sold": _make_existing(2, "url-vendor-sold", in_stock=True),
        "url-vendor-recatted": _make_existing(3, "url-vendor-recatted", in_stock=True),
    }
    items = [_make_item("url-still-in-scrape", in_stock=True)]
    per_item, cohort_oos = classify(
        items,
        existing_by_url,
        cohort_oos_at_persist=True,
        filtered_urls={"url-vendor-recatted"},
    )
    # BOTH absences flip — plain absence and filter-rejection are the same
    # admitted-set exit under the CTK-106 contract.
    assert len(cohort_oos) == 2
    assert {d.item["product_url"] for d in cohort_oos} == {
        "url-vendor-sold",
        "url-vendor-recatted",
    }
    for d in cohort_oos:
        assert d.decision == "oos"
        assert d.item["in_stock"] is False


def test_filtered_then_readmitted_fires_restocked():
    """CTK-106 verify-pass 3 — restock symmetry (D-5): a row that flipped
    OOS via filter-rejection re-enters the admitted set (operator relaxes
    the filter / vendor recats back) and fires 'restocked' through the
    existing per-item branch. No new code path — symmetry is free."""
    # State after the filtered-flip run: row sits in_stock=false in DB.
    existing_by_url = {
        "url-readmitted": _make_existing(1, "url-readmitted", in_stock=False, current_price="25.00"),
    }
    # Next run: parser admits it again (present in items, no longer filtered).
    items = [_make_item("url-readmitted", in_stock=True, current_price="25.00")]
    per_item, cohort_oos = classify(
        items,
        existing_by_url,
        cohort_oos_at_persist=True,
        filtered_urls=set(),
    )
    assert len(per_item) == 1
    assert per_item[0].decision == "restocked"
    assert cohort_oos == []


def test_filtered_flips_count_toward_flip_cap():
    """CTK-106 verify-pass 4 — guard routing (D-3): filtered-flips join
    cohort_oos_decisions, so they count toward the Stage-5.65 flip cap with
    no separate accounting. An over-cap filtered set (overbroad YAML edit)
    trips the cap and _apply_cohort_gate drops the whole cohort list
    cleanly — per-item decisions untouched."""
    n = 60  # default cap is max(50, 0.25 * prev_in_stock) = 50 at prev=60
    existing_by_url = {
        f"url-{i}": _make_existing(i, f"url-{i}", in_stock=True) for i in range(n)
    }
    items: list[dict] = []  # nothing admitted this run
    filtered = {f"url-{i}" for i in range(n)}  # ALL absences are filter-rejections
    per_item, cohort_oos = classify(
        items, existing_by_url, cohort_oos_at_persist=True, filtered_urls=filtered,
    )
    assert len(cohort_oos) == n  # filtered-flips ARE cohort flips

    cap = _resolve_flip_cap({}, prev_in_stock=n)
    assert cap == 50
    assert _flip_cap_tripped(len(cohort_oos), cap) is True

    counters = Counters(seen=0, oos=0)
    decisions, cohort_safe = _apply_cohort_gate(
        per_item, cohort_oos, counters,
        canary_tripped=False,
        matcher_error_count=0,
        cohort_unsafe_partial=False,
        completeness_degraded=False,
        flip_cap_tripped=True,
    )
    assert cohort_safe is False
    assert decisions == per_item  # cohort dropped cleanly
    assert counters.oos == 0


def test_truncated_filtered_set_adds_no_flips():
    """CTK-106 verify-pass 5 — truncation safety: filtered_urls no longer
    gates membership, so a shrunken set from a partial fetch cannot change
    decisions — flips are driven by absence from seen_urls alone, guarded
    by the existing completeness + cap rails. Full vs. truncated vs. empty
    filtered sets must classify identically."""
    existing_by_url = {
        f"url-{i}": _make_existing(i, f"url-{i}", in_stock=True) for i in range(1, 6)
    }
    items = [_make_item("url-1", in_stock=True), _make_item("url-2", in_stock=True)]

    def run(filtered):
        per_item, cohort = classify(
            items, existing_by_url, cohort_oos_at_persist=True, filtered_urls=filtered,
        )
        return (
            [(d.item["product_url"], d.decision) for d in per_item],
            sorted((d.item["product_url"], d.decision, d.existing_id) for d in cohort),
        )

    full = run({"url-3", "url-4", "url-5"})
    truncated = run({"url-3"})  # partial fetch shrank the set
    empty = run(set())
    assert full == truncated == empty


def test_byte_equivalence_empty_filtered_set():
    """CTK-106 verify-pass 6 — byte-equivalence: with an empty/absent
    filtered set, classify produces identical decisions to the pre-CTK-106
    predicate (`url not in empty_set` was vacuously true, so deleting the
    clause is a no-op on every run that filters nothing)."""
    existing_by_url = {
        "url-present": _make_existing(1, "url-present", in_stock=True),
        "url-absent": _make_existing(2, "url-absent", in_stock=True),
        "url-already-oos": _make_existing(3, "url-already-oos", in_stock=False),
    }
    items = [_make_item("url-present", in_stock=True)]

    per_item_none, cohort_none = classify(
        items, existing_by_url, cohort_oos_at_persist=True,
    )
    per_item_empty, cohort_empty = classify(
        items, existing_by_url, cohort_oos_at_persist=True, filtered_urls=set(),
    )
    for per_item, cohort in ((per_item_none, cohort_none), (per_item_empty, cohort_empty)):
        assert [d.decision for d in per_item] == ["unchanged"]
        assert len(cohort) == 1
        assert cohort[0].item["product_url"] == "url-absent"  # already-OOS row skipped


def test_filtered_urls_default_none_is_empty_set():
    """Backward-compat: classify() with no filtered_urls kwarg treats it as
    empty set — callers that don't pass the parameter get plain absent-set
    behavior (unchanged across CTK-094 fold #4 and the CTK-106 retirement)."""
    existing_by_url = {
        "url-absent": _make_existing(1, "url-absent", in_stock=True),
    }
    items: list[dict] = []
    # No filtered_urls arg
    per_item, cohort_oos = classify(items, existing_by_url, cohort_oos_at_persist=True)
    assert len(cohort_oos) == 1  # nothing filtered → URL is treated as cohort-OOS


# ---------------------------------------------------------------------------
# Fold #12 — _apply_cohort_gate unit tests
# ---------------------------------------------------------------------------


def _gate_inputs(per_item_n: int = 5, cohort_n: int = 3):
    """Helper — builds per_item + cohort decisions + counters with known
    shapes so each gate test can assert exact post-state values."""
    per_item = [
        ItemDecision(item={"product_url": f"url-p{i}"}, decision="unchanged", existing_id=i)
        for i in range(per_item_n)
    ]
    cohort = [
        ItemDecision(
            item={"product_url": f"url-c{i}", "in_stock": False, "current_price": None},
            decision="oos",
            existing_id=100 + i,
        )
        for i in range(cohort_n)
    ]
    counters = Counters(seen=per_item_n, oos=0)
    return per_item, cohort, counters


def test_apply_cohort_gate_canary_tripped_drops_cohort():
    """CTK-094 fold #12 — canary_tripped=True drops cohort decisions; per-item
    list passes through unchanged; counters.seen stays at per-item count
    (fold #1 invariant); counters.oos NOT incremented."""
    per_item, cohort, counters = _gate_inputs(per_item_n=5, cohort_n=3)
    decisions, cohort_safe = _apply_cohort_gate(
        per_item, cohort, counters,
        canary_tripped=True,
        matcher_error_count=0,
        cohort_unsafe_partial=False,
        completeness_degraded=False,
        flip_cap_tripped=False,
    )
    assert cohort_safe is False
    assert decisions == per_item  # cohort dropped
    assert len(decisions) == 5
    assert counters.seen == 5  # unchanged
    assert counters.oos == 0   # NOT incremented


def test_apply_cohort_gate_matcher_errors_drops_cohort():
    """CTK-094 fold #12 — matcher_error_count > 0 drops cohort decisions
    (status would be 'partial' per arch §3.2; cohort doesn't fire on
    partial-success either)."""
    per_item, cohort, counters = _gate_inputs(per_item_n=5, cohort_n=3)
    decisions, cohort_safe = _apply_cohort_gate(
        per_item, cohort, counters,
        canary_tripped=False,
        matcher_error_count=2,
        cohort_unsafe_partial=False,
        completeness_degraded=False,
        flip_cap_tripped=False,
    )
    assert cohort_safe is False
    assert decisions == per_item
    assert counters.oos == 0


def test_apply_cohort_gate_partial_category_drops_cohort():
    """CTK-094 fold #5 + #12 — cohort_unsafe_partial=True (raised by
    parse_bigcommerce PartialCategoryWarning on silent-zero category drift)
    drops cohort decisions. Prevents mass-false-OOS when a single category
    silently empties via template override while siblings stay healthy."""
    per_item, cohort, counters = _gate_inputs(per_item_n=5, cohort_n=3)
    decisions, cohort_safe = _apply_cohort_gate(
        per_item, cohort, counters,
        canary_tripped=False,
        matcher_error_count=0,
        cohort_unsafe_partial=True,
        completeness_degraded=False,
        flip_cap_tripped=False,
    )
    assert cohort_safe is False
    assert decisions == per_item
    assert counters.oos == 0


def test_apply_cohort_gate_all_clear_fires_cohort():
    """CTK-094 fold #12 — clean run: canary silent, no matcher errors, no
    partial-category warning → cohort decisions append to the decisions
    list AND counters.oos increments by cohort cardinality. counters.seen
    stays at per-item count (fold #1 invariant)."""
    per_item, cohort, counters = _gate_inputs(per_item_n=5, cohort_n=3)
    decisions, cohort_safe = _apply_cohort_gate(
        per_item, cohort, counters,
        canary_tripped=False,
        matcher_error_count=0,
        cohort_unsafe_partial=False,
        completeness_degraded=False,
        flip_cap_tripped=False,
    )
    assert cohort_safe is True
    assert len(decisions) == 8  # 5 per-item + 3 cohort
    assert decisions[:5] == per_item
    assert decisions[5:] == cohort
    assert counters.seen == 5   # fold #1: NOT inflated by cohort
    assert counters.oos == 3    # incremented by cohort cardinality


def test_apply_cohort_gate_empty_cohort_is_noop_on_success():
    """CTK-094 fold #12 — clean run with no cohort decisions (e.g., 8 stable-
    catalog vendors): gate returns cohort_safe=True but decisions == per_item
    (empty cohort list extends to no-op). counters unchanged."""
    per_item, _, counters = _gate_inputs(per_item_n=5, cohort_n=0)
    decisions, cohort_safe = _apply_cohort_gate(
        per_item, [], counters,
        canary_tripped=False,
        matcher_error_count=0,
        cohort_unsafe_partial=False,
        completeness_degraded=False,
        flip_cap_tripped=False,
    )
    assert cohort_safe is True
    assert decisions == per_item
    assert counters.seen == 5
    assert counters.oos == 0


def test_apply_cohort_gate_completeness_degraded_drops_cohort():
    """CTK-120 D-1 — completeness_degraded=True (pages_fetched below 50% of
    the 7d pages median; the 20-99% partial-fetch band the canary misses)
    independently drops cohort decisions. Per-item list passes through
    unchanged (real observations of really-fetched items stay trusted);
    counters.oos NOT incremented."""
    per_item, cohort, counters = _gate_inputs(per_item_n=5, cohort_n=3)
    decisions, cohort_safe = _apply_cohort_gate(
        per_item, cohort, counters,
        canary_tripped=False,
        matcher_error_count=0,
        cohort_unsafe_partial=False,
        completeness_degraded=True,
        flip_cap_tripped=False,
    )
    assert cohort_safe is False
    assert decisions == per_item
    assert len(decisions) == 5
    assert counters.seen == 5
    assert counters.oos == 0


def test_apply_cohort_gate_flip_cap_tripped_drops_cohort():
    """CTK-120 D-2 — flip_cap_tripped=True (cohort absent-set exceeds the
    per-run flip cap, whatever the cause) independently drops cohort
    decisions. Per-item list untouched; counters.oos NOT incremented."""
    per_item, cohort, counters = _gate_inputs(per_item_n=5, cohort_n=3)
    decisions, cohort_safe = _apply_cohort_gate(
        per_item, cohort, counters,
        canary_tripped=False,
        matcher_error_count=0,
        cohort_unsafe_partial=False,
        completeness_degraded=False,
        flip_cap_tripped=True,
    )
    assert cohort_safe is False
    assert decisions == per_item
    assert len(decisions) == 5
    assert counters.seen == 5
    assert counters.oos == 0


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
        test_operator_tighten_filtered_url_flips,
        test_vendor_recat_filtered_url_flips,
        test_filtered_then_readmitted_fires_restocked,
        test_filtered_flips_count_toward_flip_cap,
        test_truncated_filtered_set_adds_no_flips,
        test_byte_equivalence_empty_filtered_set,
        test_filtered_urls_default_none_is_empty_set,
        test_apply_cohort_gate_canary_tripped_drops_cohort,
        test_apply_cohort_gate_matcher_errors_drops_cohort,
        test_apply_cohort_gate_partial_category_drops_cohort,
        test_apply_cohort_gate_all_clear_fires_cohort,
        test_apply_cohort_gate_empty_cohort_is_noop_on_success,
        test_apply_cohort_gate_completeness_degraded_drops_cohort,
        test_apply_cohort_gate_flip_cap_tripped_drops_cohort,
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
