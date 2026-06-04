"""scrapers/tests/test_wwc_parse.py — CTK-037 parse-layer tests for WWC's
Shopify /products.json shape against locked fixture
scrapers/tests/fixtures/wwc/products.sample.json.

Parse-only — no DB, no network. Covers:
  - parse_shopify._normalize_product output shape per CTK-025 lock
  - parse_shopify._should_keep CTK-037 category-filter gate (WWC allowlist —
    Frag / VP Frags / WYSIWYG Frag / WWC Colony / Pack / etc; tag_denylist
    empty because Fish has its own product_type)
  - html_hash sentinel computation per arch §2.6

Inherits CTK-026 test_tsa_parse.py fixture-precedent shape. Closes
open-items.md line 48 "WWC parse-layer test retrofit" as CTK-037 co-benefit.

Runnable as:
  python -m scrapers.tests.test_wwc_parse
"""

from __future__ import annotations

import hashlib
import json
import sys
import traceback
from pathlib import Path

from decimal import Decimal

from scrapers.common.parse_shopify import _normalize_product, _should_keep


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "wwc" / "products.sample.json"
BASE_URL = "https://worldwidecorals.com"
ORIGINATOR_PREFIX = "wwc"  # CTK-025 D3 lock — matcher §3.4 stage 3 synthesizes wwc-prefix
IMAGE_STRATEGY = "mirror"

# Mirrors scrapers/vendors/wwc.yaml category_filter block (CTK-037 2026-05-10;
# CTK-119 2026-06-04). Hand-mirror — keep byte-exact with the YAML (CTK-115
# parity assertion pending). CTK-119 note: the CTK-107 chaeto/macroalgae
# title_denylist entries (YAML 2026-06-02) were missing from this mirror
# until 2026-06-04 — exactly the drift class CTK-115 will pin; repaired here.
WWC_CATEGORY_FILTER = {
    "product_type_allowlist": [
        "CTO Corals", "Featured Livestock", "Frag", "Frag-PoS", "Live Sale Coral",
        "Pack", "VP Colonies", "VP Frags", "Wholesale Frag", "WWC Colony",
        "WYSIWYG Frag",
    ],
    "tag_denylist": [],
    # CTK-107 D-2-quater fleet chaeto/macroalgae (4) + CTK-119 D-1 promo/POS/
    # BOGO dead-route tail (7, exact-compound, ids 15744-15800).
    "title_denylist": [
        "Chaeto", "Cheato", "Macroalgae", "Macro Algae",
        "Acro Frag POS", "Special Sale - Frag", "BOGO Beginner SPS Frag",
        "$10 GSP Frag", "Favia/Favites BOGO", "May $25 Build A Monti Pack",
        "Rainbow Hammer January Special",
    ],
    # CTK-119 D-1 anchored wholesale/live-sale channel-prefix axis.
    "title_denylist_prefix": ["WS - "],
}

# Mirrors scrapers/vendors/wwc.yaml auction_detection block (CTK-041 D-1 lean
# (b), Session 1 2026-05-18). Tag match is primary; slug_suffix is sanity
# log-warning when suffix-only matches surface tag-shape drift.
WWC_AUCTION_DETECTION = {
    "tags": ["Auction", "active_bidding", "on_auction"],
    "slug_suffix": "-auc",
}


def _load_fixture() -> list[dict]:
    with FIXTURE_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)["products"]


# CTK-039 pytest fixture wrapper — exposes the script-mode `_load_fixture()`
# return value as a pytest fixture so collected `def test_X(products)` test
# functions resolve cleanly under `pytest scrapers/tests/`. Script-mode
# invocation (`python -m scrapers.tests.test_wwc_parse`) continues to work
# via main()'s direct `_load_fixture()` call; the pytest decorator is
# metadata-only in that path.
try:
    import pytest
    @pytest.fixture(scope="module")
    def products():
        return _load_fixture()
except ImportError:
    pass


def _by_title(products: list[dict], title: str) -> dict:
    for p in products:
        if p["title"] == title:
            return p
    raise KeyError(f"fixture missing product titled {title!r}")


def _normalize(p: dict, auction_detection: dict | None = None) -> dict:
    return _normalize_product(p, BASE_URL, IMAGE_STRATEGY, ORIGINATOR_PREFIX, auction_detection)


# Test 1: html_hash sentinel
def test_html_hash_first_product_keys(products):
    first = products[0]
    keys = sorted(first.keys())
    expected_keys = [
        "body_html", "created_at", "handle", "id", "images", "options",
        "product_type", "published_at", "tags", "title", "updated_at",
        "variants", "vendor",
    ]
    assert keys == expected_keys, (
        f"first-product key set drift — expected {expected_keys}, got {keys}"
    )
    sha = hashlib.sha256(",".join(keys).encode("utf-8")).hexdigest()
    assert len(sha) == 64


# Test 2: filter keeps Frag (coral)
def test_filter_keeps_wwc_frag(products):
    p = _by_title(products, "WWC Avocado Smasher Zoanthids")
    assert _should_keep(p, WWC_CATEGORY_FILTER) is True


# Test 3: filter keeps VP Frags (coral)
def test_filter_keeps_wwc_vp_frags(products):
    p = _by_title(products, "JF Acid Reflux Zoanthids")
    assert _should_keep(p, WWC_CATEGORY_FILTER) is True


# Test 4: filter keeps WYSIWYG Frag (coral)
def test_filter_keeps_wwc_wysiwyg_frag(products):
    p = _by_title(products, "WYSIWYG Acropora Frag Pack")
    assert _should_keep(p, WWC_CATEGORY_FILTER) is True


# Test 5: filter rejects Fish product_type (cleanly siloed at WWC)
def test_filter_rejects_wwc_fish(products):
    """WWC's Fish product_type is the cleanest single-type denial in Phase 1.
    444 items / ~23% of catalog rejected by allowlist alone — no tag-denylist
    needed."""
    p = _by_title(products, "Yellow Tang Hawaii")
    assert _should_keep(p, WWC_CATEGORY_FILTER) is False


# Test 6: filter rejects Dry Goods (equipment)
def test_filter_rejects_wwc_dry_goods(products):
    p = _by_title(products, "Red Sea Reefer 250 Aquarium")
    assert _should_keep(p, WWC_CATEGORY_FILTER) is False


# Test 7: filter is permissive when no category_filter block
def test_filter_wwc_permissive_when_no_block(products):
    for p in products:
        assert _should_keep(p, None) is True
        assert _should_keep(p, {}) is True


# Test 8: skip-count across WWC fixture matches expected (2 of 8 denied)
def test_filter_wwc_skip_count_matches(products):
    """WWC fixture composition: 3 coral (Frag, VP Frags, WYSIWYG Frag) +
    2 non-coral (Fish, Dry Goods) + 3 CTK-041 auction rows (kept; auctions
    are in scope for /new per Jon 2026-05-14 directive; null-out happens at
    _normalize_product, not _should_keep). Expected: 6 kept, 2 skipped."""
    kept = sum(1 for p in products if _should_keep(p, WWC_CATEGORY_FILTER))
    skipped = sum(1 for p in products if not _should_keep(p, WWC_CATEGORY_FILTER))
    assert kept == 6, f"expected 6 kept, got {kept}"
    assert skipped == 2, f"expected 2 skipped, got {skipped}"


# Test 9: product_url absolute per CTK-033 D1 anchor
def test_wwc_product_url_absolute(products):
    for p in products:
        out = _normalize(p)
        assert out["product_url"].startswith(BASE_URL + "/products/"), (
            f"product_url not absolute for {p['title']!r}: {out['product_url']!r}"
        )


# Test 10: currency USD default
def test_wwc_currency_usd_default(products):
    for p in products:
        assert _normalize(p)["currency"] == "USD"


# Test 11: vendor_image_url is images[0].src
def test_wwc_vendor_image_url_first_image(products):
    p = _by_title(products, "WWC Avocado Smasher Zoanthids")
    out = _normalize(p)
    assert out["vendor_image_url"] == p["images"][0]["src"]


# Test 12: in_stock toggles correctly with variants.available
def test_wwc_in_stock_semantics(products):
    p_in = _by_title(products, "WWC Avocado Smasher Zoanthids")
    p_oos = _by_title(products, "JF Acid Reflux Zoanthids")
    assert _normalize(p_in)["in_stock"] is True
    assert _normalize(p_oos)["in_stock"] is False


# CTK-041 Test 13: auction with `Auction` tag → current_price null-out
def test_auction_tag_nulls_price(products):
    """D-1 lean (b) — auction_detection block in YAML threads through
    fetch_and_parse into _normalize_product; tag-set match is primary signal.
    Variant placeholder price ($249) coerced to None so frontend renders
    "price on request" via formatPrice(null) per Jon 2026-05-14 directive."""
    p = _by_title(products, "Raspberry Pie Bowerbanki Auction 7916")
    out = _normalize(p, WWC_AUCTION_DETECTION)
    assert out["current_price"] is None


# CTK-041 Test 14: auction with `active_bidding` tag → current_price null-out
def test_auction_active_bidding_tag_nulls_price(products):
    """Tag-set match against any single auction tag fires; multi-tag set
    membership is union not intersection."""
    p = _by_title(products, "Active Bidding Acan 8021")
    out = _normalize(p, WWC_AUCTION_DETECTION)
    assert out["current_price"] is None


# CTK-041 Test 15: suffix-only match logs warning, does NOT null-out price
def test_auction_suffix_only_logs_warning_preserves_price(products):
    """Tag-shape drift case — slug ends with -auc but no auction tag present.
    _is_auction returns False (tag-match is primary) but emits a warning so
    the regression surfaces in observability. Price preserved to avoid
    silently re-pricing a non-auction listing on tag-set drift.

    Uses a custom logging.Handler so the assertion works under both pytest
    collection and script-mode `python -m scrapers.tests.test_wwc_parse`."""
    import logging
    parse_log = logging.getLogger("scrapers.common.parse_shopify")
    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _Capture(level=logging.WARNING)
    parse_log.addHandler(handler)
    prev_level = parse_log.level
    parse_log.setLevel(logging.WARNING)
    try:
        p = _by_title(products, "Tag-Drift Suffix-Only Auction")
        out = _normalize(p, WWC_AUCTION_DETECTION)
    finally:
        parse_log.removeHandler(handler)
        parse_log.setLevel(prev_level)

    assert out["current_price"] == Decimal("99.00"), f"expected price preserved, got {out['current_price']!r}"
    messages = [rec.getMessage() for rec in records]
    assert any("slug_suffix=-auc" in m for m in messages), (
        f"expected slug_suffix warning, got: {messages}"
    )


# CTK-041 Test 16: non-auction listings preserve price under auction_detection
def test_non_auction_preserves_price(products):
    """Permissive baseline — listings without auction tag or -auc suffix get
    coerce_price'd to a real float; the auction_detection block is a no-op
    for them."""
    p = _by_title(products, "WWC Avocado Smasher Zoanthids")
    out = _normalize(p, WWC_AUCTION_DETECTION)
    assert out["current_price"] == Decimal("79.99"), f"expected 79.99, got {out['current_price']!r}"


# CTK-119 Test 18: anchored prefix axis rejects title-initial WS - class
def test_filter_rejects_ws_prefix(products):
    """CTK-119 D-1 — the WS - wholesale/live-sale channel class (56 of 523
    user-facing rows, all title-initial, dead retail routes per
    head-sweep-2026-06-04.txt) rejects on the title_denylist_prefix axis.
    Case shape pinned both directions per the CTK-096 lowercase-runtime
    convention."""
    for title in ("WS - Acro Frag Pack", "WS - $2 Zoa Frag", "ws - lowercase drift"):
        product = {
            "title": title,
            "product_type": "Wholesale Frag",
            "tags": [],
            "variants": [{"available": True}],
        }
        assert _should_keep(product, WWC_CATEGORY_FILTER) is False, (
            f"title-initial {title!r} should reject on the prefix axis; product passed"
        )


# CTK-119 Test 19: anchored semantics — the substring collision class survives
def test_filter_keeps_word_final_ws_collision_class(products):
    """CTK-119 review-fold #1 false-kill guard — executable rationale for the
    prefix axis over a substring entry. Titles carrying word-final "ws"
    before " - " must SURVIVE: a substring 'WS - ' entry would kill all three
    synthetics below, silently, at intake. A regression that reimplements the
    axis as substring matching (or moves the entry to title_denylist) breaks
    this test."""
    title_denylist_lc = [e.lower() for e in WWC_CATEGORY_FILTER["title_denylist"]]
    for title in ("Rainbows - WYSIWYG Frag", "Jaws - 2 inch Colony", "Outlaws - Zoa Pack"):
        assert not any(e in title.lower() for e in title_denylist_lc), (
            "self-check: synthetic title must carry no title_denylist substring, "
            "or this test stops isolating the prefix axis"
        )
        product = {
            "title": title,
            "product_type": "Frag",
            "tags": [],
            "variants": [{"available": True}],
        }
        assert _should_keep(product, WWC_CATEGORY_FILTER) is True, (
            f"word-final-ws title {title!r} false-killed — anchored semantics regressed"
        )


# CTK-119 Test 20: promo tail exact-compound entries reject, one per entry
def test_filter_rejects_promo_tail_exact_titles(products):
    """CTK-119 D-1 — each of the 7 promo/POS/BOGO dead-route titles rejects
    via its own exact-compound title_denylist entry. One synthetic per entry
    (CTK-104 reef-safety family shape) so a YAML/mirror drop of any single
    entry breaks this test. PT held at allowlisted 'Frag' to isolate the
    title axis."""
    for title in (
        "Acro Frag POS", "Special Sale - Frag", "BOGO Beginner SPS Frag",
        "$10 GSP Frag", "Favia/Favites BOGO", "May $25 Build A Monti Pack",
        "Rainbow Hammer January Special",
    ):
        product = {
            "title": title,
            "product_type": "Frag",
            "tags": [],
            "variants": [{"available": True}],
        }
        assert _should_keep(product, WWC_CATEGORY_FILTER) is False, (
            f"promo title {title!r} should reject via its exact-compound entry; product passed"
        )


# CTK-119 Test 21: coral false-kill guard across the real-shape fixture surface
def test_filter_keeps_corals_post_ctk119(products):
    """CTK-119 D-1 false-kill guard — the 3 real-shape coral fixtures pass the
    full post-CTK-119 mirror (11 title entries + prefix axis). Pins the new
    entries against the coral surface the same way CTK-104's guard pinned the
    reef-safety family on TSA."""
    for title in (
        "WWC Avocado Smasher Zoanthids",
        "JF Acid Reflux Zoanthids",
        "WYSIWYG Acropora Frag Pack",
    ):
        assert _should_keep(_by_title(products, title), WWC_CATEGORY_FILTER) is True, (
            f"coral fixture {title!r} false-killed by the CTK-119 entries"
        )


# CTK-041 Test 17: auction_detection=None is no-op (permissive default)
def test_auction_detection_none_is_noop(products):
    """Per-vendor opt-in shape — vendors without auction_detection block in
    YAML get the None default; _normalize_product skips the null-out branch
    even when an auction-tagged product appears."""
    p = _by_title(products, "Raspberry Pie Bowerbanki Auction 7916")
    out = _normalize(p, None)
    assert out["current_price"] == Decimal("249.00"), f"expected 249.00 preserved, got {out['current_price']!r}"


def main() -> int:
    products = _load_fixture()
    print(f"loaded fixture: {len(products)} products from {FIXTURE_PATH}")

    tests = [
        test_html_hash_first_product_keys,
        test_filter_keeps_wwc_frag,
        test_filter_keeps_wwc_vp_frags,
        test_filter_keeps_wwc_wysiwyg_frag,
        test_filter_rejects_wwc_fish,
        test_filter_rejects_wwc_dry_goods,
        test_filter_wwc_permissive_when_no_block,
        test_filter_wwc_skip_count_matches,
        test_wwc_product_url_absolute,
        test_wwc_currency_usd_default,
        test_wwc_vendor_image_url_first_image,
        test_wwc_in_stock_semantics,
        test_auction_tag_nulls_price,
        test_auction_active_bidding_tag_nulls_price,
        test_auction_suffix_only_logs_warning_preserves_price,
        test_non_auction_preserves_price,
        test_filter_rejects_ws_prefix,
        test_filter_keeps_word_final_ws_collision_class,
        test_filter_rejects_promo_tail_exact_titles,
        test_filter_keeps_corals_post_ctk119,
        test_auction_detection_none_is_noop,
    ]

    failures: list[tuple[str, str]] = []
    for fn in tests:
        name = fn.__name__
        try:
            fn(products)
            print(f"  [PASS] {name}")
        except AssertionError as e:
            print(f"  [FAIL] {name}: {e}")
            failures.append((name, str(e)))
        except Exception as e:  # noqa: BLE001
            print(f"  [ERROR] {name}: {type(e).__name__}: {e}")
            traceback.print_exc()
            failures.append((name, f"{type(e).__name__}: {e}"))

    print()
    if failures:
        print(f"{len(failures)}/{len(tests)} tests failed:")
        for name, msg in failures:
            print(f"  - {name}: {msg[:200]}")
        return 1
    print(f"all {len(tests)} tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
