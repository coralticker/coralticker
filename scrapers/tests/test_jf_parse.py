"""scrapers/tests/test_jf_parse.py — CTK-027 parse-layer tests for JF's
Shopify /products.json shape against locked fixture
scrapers/tests/fixtures/jf/products.sample.json.

Parse-only — no DB, no network. Validates parse_shopify._normalize_product
output shape + html_hash sentinel computation across eight curated JF
products covering: longform JASON FOX prefix (LPS), collab-prefix coral
(ORA, OOS), JF-prefix coral OOS (WYSIWYG), bare-name coral (no-prefix,
matcher §3.4 stage 3 case), JF-prefix coral in-stock (SPS), empty
product_type real coral (Q-8 path (a) recovery — Jason Fox longform), multi-
variant merch (T Shirt, 19 variants), empty product_type test-data (LS_APR_2022
archived; frontend has_image filter excludes downstream).

Supersedes the CTK-037 Session 2 pre-staged synthetic fixture + tests (which
carried "ORIGINATOR_PREFIX='jf' is provisional pending CTK-027 Session 1
final decision" in their own docstring) with real-catalog data captured
2026-05-11 + test coverage reflecting actual JF site shape (ALL-CAPS titles,
60% JF-prefix-bearing rate, partial matcher §3.4 stage 3 case coverage).

Runnable as:
  python -m scrapers.tests.test_jf_parse

Fixture regen path documented in scrapers/vendors/jf.py docstring (CTK-024/
025/026/027 convention).

Coverage:
  test_html_hash_first_product_keys                      arch §2.6 sentinel
  test_jf_prefix_coral_normalize_preserves_prefix        decision #18
  test_no_prefix_coral_normalize_no_synthesis            stage 3 input shape
  test_oos_product_in_stock_false                        variants.available
  test_in_stock_product_in_stock_true                    variants.available
  test_multi_variant_merch_in_stock_any                  any-available logic
  test_first_sku_pick                                    parse first-SKU select
  test_product_url_absolute                              CTK-033 D1 anchor
  test_vendor_image_url_first_image                      images[0].src
  test_currency_usd_default                              Q1-3 lock
  test_lineage_flag_all_caps_titles_stay_unknown         JF ALL-CAPS shape
  test_category_inference                                arch §1.4 enum
  test_filter_keeps_jf_sps_coral                         CTK-037 allowlist hit
  test_filter_keeps_jf_lps_coral                         CTK-037 allowlist hit
  test_filter_keeps_jf_empty_product_type_real_coral     CTK-037 Session 5 Q-8 (a)
  test_filter_keeps_jf_empty_product_type_test_data      filter passes; frontend excludes
  test_filter_rejects_jf_tshirt_merch                    allowlist miss
  test_filter_jf_permissive_when_no_block                Phase 2 inheritance
  test_filter_jf_skip_count_matches                      fixture composition pin
  test_filter_normalizes_none_product_type_to_empty_string  CTK-037 Session 5.5
  test_filter_rejects_none_product_type_when_empty_not_in_allowlist  symmetric
"""

from __future__ import annotations

import hashlib
import json
import sys
import traceback
from pathlib import Path

from scrapers.common.parse_shopify import _normalize_product, _should_keep


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "jf" / "products.sample.json"
BASE_URL = "https://jasonfoxsignaturecorals.com"
ORIGINATOR_PREFIX = "jf"  # matches scrapers/vendors/jf.yaml D4 lock
IMAGE_STRATEGY = "mirror"

# Mirrors scrapers/vendors/jf.yaml category_filter block (CTK-027 2026-05-11;
# inherits CTK-037 Session 5 empty-string allowlist for the empty-product_type
# bucket containing 1 real coral + 3 LS_APR_2022 archived/test-data; frontend
# has_image filter excludes the test-data downstream).
JF_CATEGORY_FILTER = {
    "product_type_allowlist": [
        "", "Chalices", "LPS", "MYSTERY BOX", "SPS", "WYSIWYG",
        "Zoanthids/Softies",
    ],
    "tag_denylist": [],
}


def _load_fixture() -> list[dict]:
    with FIXTURE_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)["products"]


def _by_title(products: list[dict], title: str) -> dict:
    for p in products:
        if p["title"] == title:
            return p
    raise KeyError(f"fixture missing product titled {title!r}")


def _normalize(p: dict) -> dict:
    return _normalize_product(p, BASE_URL, IMAGE_STRATEGY, ORIGINATOR_PREFIX)


# ─── Test 1: html_hash sentinel — sorted-keys-of-first-product SHA256 ─────────
def test_html_hash_first_product_keys(products):
    """Arch §2.6 Shopify variant: hash sorted key set of first product object.
    F5 fold (sort-before-hash) in parse_shopify.py:82 — Shopify can change JSON
    key emission order across versions without a real schema change; sorting
    collapses ordering noise. The hash flips ONLY when keys are added/removed.
    """
    first = products[0]
    keys = sorted(first.keys())
    expected = hashlib.sha256(",".join(keys).encode("utf-8")).hexdigest()
    # Empirical anchor: 13 keys per smoke 2026-05-11. PE+WWC+TSA also have 13.
    assert len(keys) == 13, (
        f"expected 13 keys on first product (matches PE+WWC+TSA empirical "
        f"anchor), got {len(keys)}: {keys}"
    )
    expected_keys = [
        "body_html", "created_at", "handle", "id", "images", "options",
        "product_type", "published_at", "tags", "title", "updated_at",
        "variants", "vendor",
    ]
    assert keys == expected_keys, (
        f"first-product key set drift — expected {expected_keys}, got {keys}. "
        f"If a key was added/removed, the html_hash sentinel will flip and "
        f"scraper_runs.error_class='html_schema_change' will fire next scrape."
    )
    assert len(expected) == 64, f"SHA256 hex digest is 64 chars; got {len(expected)}"


# ─── Test 2: JF-prefix coral — normalize PRESERVES prefix per decision #18 ────
def test_jf_prefix_coral_normalize_preserves_prefix(products):
    """Per decision #18 (§3.2 cascade fix): vendor prefix is preserved in
    normalized_title. The matcher §3.4 stage 3 prepends originator_prefix at
    match-time for no-prefix titles; it does NOT strip an existing prefix from
    prefix-bearing titles. originator_prefix YAML config does not affect
    normalize_title output (decision #23 + decision #18 interaction).

    JF titles are ALL-CAPS; normalize_title lowercases so "JF AUTUMN BLAZE
    ACRO" → "jf autumn blaze acro" (prefix preserved as lowercase 'jf').
    """
    p = _by_title(products, "JF AUTUMN BLAZE ACRO")
    out = _normalize(p)
    assert out["raw_title"] == "JF AUTUMN BLAZE ACRO"
    assert out["normalized_title"] == "jf autumn blaze acro", (
        f"prefix should be preserved (lowercase only); got {out['normalized_title']!r}"
    )


# ─── Test 3: no-prefix coral — normalize_title is bare (matcher §3.4 stage 3) ─
def test_no_prefix_coral_normalize_no_synthesis(products):
    """Per matcher §3.4 stage 3: no-prefix titles are normalized to bare
    ("special porites"). Stage 3 SYNTHESIZES "jf special porites" against
    canonical-prefix patterns at match-time; that synthesis lives in
    matcher.py, not parse_shopify. This test pins the parse-layer contract.
    """
    p = _by_title(products, "SPECIAL PORITES")
    out = _normalize(p)
    assert out["normalized_title"] == "special porites", (
        f"no-prefix title should normalize bare; got {out['normalized_title']!r}"
    )


# ─── Test 4: OOS product — variants.available all false → in_stock=False ──────
def test_oos_product_in_stock_false(products):
    """Arch §2.1 stage 4 in_stock semantics: any(v.get('available')) across
    variants. Between-drop window JF corals are typically OOS — fixture
    captures this realistic state. price_history diff logic depends on
    in_stock toggling correctly so price-changed-while-OOS doesn't trip a
    stock-changed event."""
    p = _by_title(products, "JF AUTUMN BLAZE ACRO")
    out = _normalize(p)
    assert out["in_stock"] is False, f"expected in_stock=False, got {out['in_stock']!r}"


# ─── Test 5: in-stock product → in_stock=True ─────────────────────────────────
def test_in_stock_product_in_stock_true(products):
    p = _by_title(products, "JF BLOODY SUNRISE MONTIPORA")
    out = _normalize(p)
    assert out["in_stock"] is True, f"expected in_stock=True, got {out['in_stock']!r}"


# ─── Test 6: multi-variant merch — any-available decides in_stock ─────────────
def test_multi_variant_merch_in_stock_any(products):
    """T Shirt with 19 size/color variants. in_stock=True if ANY variant
    available; in_stock=False only if ALL variants are unavailable. Phase 1
    stock-flip de-duplication depends on this any-semantics — a single-
    size/color restock on a multi-variant product flips in_stock True without
    false-positive 'all sizes restocked'."""
    p = _by_title(products, "T Shirt")
    variants = p.get("variants") or []
    assert len(variants) > 1, (
        f"fixture multi-variant pick should have >1 variants; got {len(variants)}"
    )
    out = _normalize(p)
    expected = any(v.get("available") for v in variants)
    assert out["in_stock"] is expected, (
        f"in_stock={out['in_stock']!r} doesn't match any(available)={expected!r}"
    )


# ─── Test 7: first-SKU pick — multi-variant merch picks variants[0].sku ───────
def test_first_sku_pick(products):
    """parse_shopify picks the FIRST non-empty SKU across variants and writes
    one vendor_listings row per product. JF's T Shirt carries intra-product
    SKU collisions (6 colors × per-size SKUs sharing tshirt-s/m/l) — but the
    first-SKU pick collapses this to one row; the 0002_drop_vendor_sku_unique
    constraint never sees the collision. Validates JF's D2 finding (no inter-
    product collisions at the row level despite 18 raw-variant duplicates)."""
    p = _by_title(products, "T Shirt")
    out = _normalize(p)
    # First variant is "Grey / Small" with sku "tshirt-s".
    assert out["vendor_sku"] == "tshirt-s", (
        f"expected first-variant SKU 'tshirt-s'; got {out['vendor_sku']!r}"
    )


# ─── Test 8: product_url is absolute (CTK-033 D1 anchor) ──────────────────────
def test_product_url_absolute(products):
    """Per CTK-033 D1 + arch §2.1 stage 4 normalize lock: product_url is
    ABSOLUTE (base_url joined to /products/<handle>). The diff.classify()
    lookup against existing_by_url depends on this — relative URLs would
    miss the dict and force-classify every existing listing as 'new' on the
    next-day scrape (price_history explosion + redundant re-mirroring)."""
    for p in products:
        out = _normalize(p)
        assert out["product_url"].startswith(BASE_URL + "/products/"), (
            f"product_url not absolute for {p['title']!r}: {out['product_url']!r}"
        )
        assert out["product_url"].endswith(p["handle"]), (
            f"product_url missing handle suffix for {p['title']!r}: {out['product_url']!r}"
        )


# ─── Test 9: vendor_image_url is images[0].src (raw, pre-mirror) ──────────────
def test_vendor_image_url_first_image(products):
    """Phase B mirror queue pulls vendor_image_url and writes image_url after
    R2 storage. Parse layer just hands over the raw vendor URL untouched."""
    p = _by_title(products, "JF BLOODY SUNRISE MONTIPORA")
    out = _normalize(p)
    expected_src = p["images"][0]["src"]
    assert out["vendor_image_url"] == expected_src, (
        f"vendor_image_url should be images[0].src; expected {expected_src!r}, "
        f"got {out['vendor_image_url']!r}"
    )


# ─── Test 10: currency = USD per Q1-3 lock ────────────────────────────────────
def test_currency_usd_default(products):
    """Phase 1 vendors all USD per Q1-3 (arch §1.4 / decision register). Parse
    layer hardcodes USD; currency-aware logic re-opens at Phase 2 if any vendor
    ships non-USD."""
    for p in products:
        out = _normalize(p)
        assert out["currency"] == "USD", (
            f"currency drift on {p['title']!r}: expected 'USD', got {out['currency']!r}"
        )


# ─── Test 11: lineage_flag — ALL-CAPS titles stay 'unknown' (JF-wide shape) ───
def test_lineage_flag_all_caps_titles_stay_unknown(products):
    """JF-specific finding: titles are ALL-CAPS-throughout ("JF AUTUMN BLAZE
    ACRO", not "JF Autumn Blaze Acro"). infer_lineage_flag's regex requires
    ALL-CAPS-prefix THEN title-case ("^[A-Z]{2,4}\\s+[A-Z][a-z]+") — it WILL
    NOT fire on JF titles. All JF rows land lineage_flag='unknown' at parse
    time. The matcher §3.4 stage 3 originator_prefix synthesis is the real
    lineage-capture mechanism for JF; lineage_flag is just a parse-layer hint
    (see normalize.infer_lineage_flag docstring + jf.py docstring callout).
    Flagged to /lead-architect at /backend-engineer Session 1 — not a fix-
    needed gap, intentional heuristic limitation.
    """
    jf_prefix = _by_title(products, "JF BLOODY SUNRISE MONTIPORA")
    no_prefix = _by_title(products, "SPECIAL PORITES")
    collab_prefix = _by_title(products, "ORA PEARLBERRY ACRO")
    longform = _by_title(products, "JASON FOX FIREWATER HYDNOPHORA")

    # All four cases land 'unknown' under the ALL-CAPS-throughout JF shape.
    assert _normalize(jf_prefix)["lineage_flag"] == "unknown", (
        "JF-prefix ALL-CAPS title should land lineage_flag='unknown' — regex "
        "needs title-case after prefix, which JF titles never satisfy"
    )
    assert _normalize(no_prefix)["lineage_flag"] == "unknown", (
        "no-prefix coral should be lineage_flag=unknown (matcher §3 does real work)"
    )
    assert _normalize(collab_prefix)["lineage_flag"] == "unknown", (
        "collab-prefix ALL-CAPS title should land lineage_flag='unknown'"
    )
    assert _normalize(longform)["lineage_flag"] == "unknown", (
        "longform 'JASON FOX ...' is 6+ char prefix — outside the 2-4 char "
        "regex window even before the title-case requirement"
    )


# ─── Test 12: category inference per arch §1.4 enum ───────────────────────────
def test_category_inference(products):
    """infer_category matches against product_type + tags + title. Arch §1.4
    enum: ('sps','lps','softie','zoa','mushroom','anemone','clam','chalice',
    'fish','invert','equipment','other'). First-hit wins; more specific
    before generic. JF's product_type carries the heavy signal ('SPS', 'LPS'
    match \\bsps\\b / \\blps\\b directly); WYSIWYG-bucketed titles like 'ACRO'
    abbreviation don't match the full-word patterns ('acropora') so they fall
    through to None — accurate parse-layer reflection of current shape."""
    sps_coral = _by_title(products, "JF BLOODY SUNRISE MONTIPORA")  # product_type=SPS
    lps_coral = _by_title(products, "JASON FOX FIREWATER HYDNOPHORA")  # product_type=LPS
    wysiwyg_acro = _by_title(products, "JF AUTUMN BLAZE ACRO")  # product_type=WYSIWYG; title abbrev 'ACRO' misses
    bare_porites = _by_title(products, "SPECIAL PORITES")  # WYSIWYG; 'Porites' not in patterns

    assert _normalize(sps_coral)["category"] == "sps", (
        f"SPS product_type should match sps; got {_normalize(sps_coral)['category']!r}"
    )
    assert _normalize(lps_coral)["category"] == "lps", (
        f"LPS product_type should match lps; got {_normalize(lps_coral)['category']!r}"
    )
    # WYSIWYG bucket + JF abbreviation titles = no category match — honest
    # reflection of current parse layer; matcher §3 + named-coral seed-load
    # are the real category-resolution path at Phase 3.
    assert _normalize(wysiwyg_acro)["category"] is None, (
        f"WYSIWYG product_type + 'ACRO' abbrev title should miss patterns; "
        f"got {_normalize(wysiwyg_acro)['category']!r}"
    )
    assert _normalize(bare_porites)["category"] is None, (
        f"WYSIWYG product_type + 'Porites' (not in patterns) should miss; "
        f"got {_normalize(bare_porites)['category']!r}"
    )


# ─── Test 13 (CTK-037): filter keeps JF-prefix SPS coral ──────────────────────
def test_filter_keeps_jf_sps_coral(products):
    """SPS product_type in allowlist + empty tag_denylist = KEEP. Anchor case
    for the 141-item SPS bucket on JF."""
    p = _by_title(products, "JF BLOODY SUNRISE MONTIPORA")
    assert _should_keep(p, JF_CATEGORY_FILTER) is True


# ─── Test 14 (CTK-037): filter keeps JF-prefix LPS coral ──────────────────────
def test_filter_keeps_jf_lps_coral(products):
    """LPS product_type in allowlist + empty tag_denylist = KEEP. Anchor case
    for the 96-item LPS bucket on JF."""
    p = _by_title(products, "JASON FOX FIREWATER HYDNOPHORA")
    assert _should_keep(p, JF_CATEGORY_FILTER) is True


# ─── Test 15 (CTK-037 Session 5 Q-8 (a)): empty-product_type real coral keeps ─
def test_filter_keeps_jf_empty_product_type_real_coral(products):
    """JF empty-product_type bucket carries 1 real coral ("Jason Fox Deep
    Purple Stag" — Stag = Staghorn = SPS coral, missing product_type tag).
    "" in allowlist per CTK-037 Session 5 Q-8 path (a) recovers this row.
    Frontend has_image filter is the downstream gate for test-data rows in
    the same bucket (see test 16)."""
    p = _by_title(products, "Jason Fox Deep Purple Stag")
    assert _should_keep(p, JF_CATEGORY_FILTER) is True


# ─── Test 16 (CTK-037 Session 5 Q-8 (a)): empty-product_type test-data keeps ──
def test_filter_keeps_jf_empty_product_type_test_data(products):
    """JF empty-product_type bucket also carries 3 LS_APR_2022 archived/test-
    data rows (vendor='gregg', tags=['limit_warning_ON', 'LS_APR_2022']). The
    "" allowlist entry passes these through at scrape time — frontend
    has_image filter excludes them downstream (most lack images). Per
    /lead-backend Session 5 spot-check 2026-05-11: tolerable scraper-side
    permissiveness because frontend gate is the load-bearing filter."""
    p = _by_title(products, "gregg is great")
    assert _should_keep(p, JF_CATEGORY_FILTER) is True


# ─── Test 17 (CTK-037): filter rejects JF tshirt merch ────────────────────────
def test_filter_rejects_jf_tshirt_merch(products):
    """T Shirt product_type='tshirt' — not in JF allowlist (coral-product_type
    only). Allowlist miss is short-circuit reject; tag_denylist never
    consulted. Distinct from TSA's pattern where merch+equipment share
    product_type='Aquarium Supplies'."""
    p = _by_title(products, "T Shirt")
    assert _should_keep(p, JF_CATEGORY_FILTER) is False


# ─── Test 18 (CTK-037): permissive default when no category_filter block ──────
def test_filter_jf_permissive_when_no_block(products):
    """Phase 2 vendor onboarding inheritance — None or {} = no gate. Every
    fixture product passes (including the T Shirt merch that the real JF
    filter rejects)."""
    for p in products:
        assert _should_keep(p, None) is True
        assert _should_keep(p, {}) is True


# ─── Test 19 (CTK-037): skip-count across JF fixture matches expected ─────────
def test_filter_jf_skip_count_matches(products):
    """JF fixture composition: 5 coral (LPS Firewater + WYSIWYG ORA Pearlberry
    + WYSIWYG JF Autumn Blaze + WYSIWYG Special Porites + SPS JF Bloody
    Sunrise) + 2 empty-product_type passes (Jason Fox Deep Purple Stag real
    coral + gregg-is-great archived) + 1 tshirt reject = 7 kept, 1 skipped."""
    kept = sum(1 for p in products if _should_keep(p, JF_CATEGORY_FILTER))
    skipped = sum(1 for p in products if not _should_keep(p, JF_CATEGORY_FILTER))
    assert kept == 7, f"expected 7 kept, got {kept}"
    assert skipped == 1, f"expected 1 skipped, got {skipped}"


# ─── Test 20 (CTK-037 Session 5.5): predicate normalization keeps None/absent ─
def test_filter_normalizes_none_product_type_to_empty_string(products):
    """CTK-037 Session 5.5 — None or key-absent product_type normalizes to "" so
    JF empty-string allowlist entry matches both Shopify shape variants.
    Prevents silent recall regression if Shopify shifts empty-bucket
    representation. Mirror of test_tsa_parse precedent."""
    product_none = {"product_type": None, "title": "Some coral", "tags": []}
    product_missing = {"title": "Some coral", "tags": []}  # key absent
    cf = JF_CATEGORY_FILTER  # has "" in allowlist
    assert _should_keep(product_none, cf) is True
    assert _should_keep(product_missing, cf) is True


# ─── Test 21 (CTK-037 Session 5.5): normalization is symmetric (rejects too) ──
def test_filter_rejects_none_product_type_when_empty_not_in_allowlist(products):
    """CTK-037 Session 5.5 — normalization is symmetric; None still rejects when
    "" is not in the allowlist. Mirror of the TSA precedent test."""
    product = {"product_type": None, "title": "Some coral", "tags": []}
    cf = {"product_type_allowlist": ["SPS"], "tag_denylist": []}
    assert _should_keep(product, cf) is False


def main() -> int:
    products = _load_fixture()
    print(f"loaded fixture: {len(products)} products from {FIXTURE_PATH}")

    tests = [
        test_html_hash_first_product_keys,
        test_jf_prefix_coral_normalize_preserves_prefix,
        test_no_prefix_coral_normalize_no_synthesis,
        test_oos_product_in_stock_false,
        test_in_stock_product_in_stock_true,
        test_multi_variant_merch_in_stock_any,
        test_first_sku_pick,
        test_product_url_absolute,
        test_vendor_image_url_first_image,
        test_currency_usd_default,
        test_lineage_flag_all_caps_titles_stay_unknown,
        test_category_inference,
        test_filter_keeps_jf_sps_coral,
        test_filter_keeps_jf_lps_coral,
        test_filter_keeps_jf_empty_product_type_real_coral,
        test_filter_keeps_jf_empty_product_type_test_data,
        test_filter_rejects_jf_tshirt_merch,
        test_filter_jf_permissive_when_no_block,
        test_filter_jf_skip_count_matches,
        test_filter_normalizes_none_product_type_to_empty_string,
        test_filter_rejects_none_product_type_when_empty_not_in_allowlist,
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
