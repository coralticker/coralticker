"""scrapers/tests/test_battlecorals_parse.py — CTK-085 parse-layer tests for
Battlecorals' Shopify /products.json shape against locked fixture
scrapers/tests/fixtures/battlecorals/products.sample.json.

Parse-only — no DB, no network. Validates parse_shopify._normalize_product
output shape + html_hash sentinel computation across eight curated
Battlecorals products covering: Battlecorals house bare-TitleCase canonical
seed-list lineage (Hyperberry — SPS, Acropora Microclados); cross-vendor
ALL-CAPS prefix coral (TSA Bill Murray — SPS, Acropora sp.; ORA Pearlberry
— SPS, Acropora); BC self-prefix outlier (BC All stars grow out 2025!!!
— live coral grow-out announcement); OOS Acropora Tenuis bare-TitleCase
(Genie of Death); empty product_type Battlebox grab-bag with null first-
variant SKU (2000.00 Battlebox Ships free); period-less Acropora sp variant
(Love SKY); empty product_type merch leak (BC Tee Shirt — frontend has_image
filter is the downstream gate per CTK-027 Session 5 Q-8 path (a)).

Coverage parity with test_jf_parse.py (CTK-027 precedent) with Battlecorals-
specific shape adjustments: lineage_flag fires on cross-vendor prefixes
(TSA / ORA / BC) — distinct from JF's ALL-CAPS-throughout shape that lands
every title at 'unknown'; first-variant SKU pick covers null-fallback case
(2000.00 Battlebox empty-variant-SKU + BC All stars empty-string fallback);
category_filter exercises taxonomic-granularity allowlist (Acropora
Microclados / Acropora sp. / Acropora sp / Acropora Tenuis / live coral)
in addition to the standard empty-bucket Q-8 (a) recovery cases.

Runnable as:
  python -m scrapers.tests.test_battlecorals_parse

Fixture regen path documented in scrapers/vendors/battlecorals.py docstring
(CTK-024/025/026/027 convention).

Coverage:
  test_html_hash_first_product_keys                       arch §2.6 sentinel (13 keys)
  test_house_lineage_normalize_no_prefix_synthesis        Hyperberry bare-TitleCase
  test_cross_vendor_prefix_lowercased_preserved           TSA / ORA prefixes preserved
  test_oos_product_in_stock_false                         Genie of Death OOS
  test_in_stock_product_in_stock_true                     Hyperberry in-stock
  test_battlebox_in_stock_with_null_sku                   empty-PT + null SKU mix
  test_first_sku_pick_falls_back_when_empty_string        BC All stars empty-string variants
  test_first_sku_pick_picks_first_non_empty               Hyperberry 3-variant SKU pick
  test_product_url_absolute                               CTK-033 D1 anchor
  test_vendor_image_url_first_image                       images[0].src
  test_currency_usd_default                               Q1-3 lock
  test_lineage_flag_cross_vendor_prefix_vendor_named      TSA / ORA / BC fire 'vendor-named'
  test_lineage_flag_bare_titlecase_stays_unknown          Hyperberry / Genie / Love SKY unknown
  test_category_inference                                 Acropora-genus → 'sps'; empty → None
  test_filter_keeps_house_lineage_acropora_microclados    CTK-037 allowlist hit
  test_filter_keeps_cross_vendor_acropora_sp_dot          CTK-037 allowlist hit
  test_filter_keeps_period_less_acropora_sp_variant       distinct allowlist entry
  test_filter_keeps_acropora_tenuis_oos                   CTK-037 allowlist hit
  test_filter_keeps_live_coral_growout                    'live coral' product_type entry
  test_filter_keeps_empty_product_type_battlebox          CTK-037 Session 5 Q-8 (a) — coral grab-bag
  test_filter_keeps_empty_product_type_merch_leak         Q-8 (a) acceptable leak; frontend has_image gate
  test_filter_battlecorals_permissive_when_no_block       Phase 2 inheritance
  test_filter_battlecorals_kept_count_matches             8 kept / 0 skipped under slim allowlist
  test_filter_normalizes_none_product_type_to_empty_string  CTK-037 Session 5.5
  test_filter_rejects_none_product_type_when_empty_not_in_allowlist  symmetric
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

from scrapers.common.parse_shopify import _normalize_product, _should_keep


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "battlecorals" / "products.sample.json"
BASE_URL = "https://battlecorals.com"
ORIGINATOR_PREFIX = "battlecorals"  # matches scrapers/vendors/battlecorals.yaml D1 lock
IMAGE_STRATEGY = "mirror"

# Slim allowlist covering only the 8 fixture products' product_types. The
# production allowlist at scrapers/vendors/battlecorals.yaml carries ~70
# entries enumerating the full empirical 2026-05-25 catalog walk; mirroring
# all 70 here would create YAML/test drift risk on every category amendment.
# Tests pin filter behavior on the entries the fixture exercises.
BC_CATEGORY_FILTER = {
    "product_type_allowlist": [
        "",                       # 2000.00 Battlebox + BC Tee Shirt (Q-8 (a))
        "Acropora",               # ORA Pearlberry
        "Acropora Microclados",   # Hyperberry (Battlecorals house canonical)
        "Acropora sp",            # Love SKY (period-less variant)
        "Acropora sp.",           # TSA Bill Murray
        "Acropora Tenuis",        # Genie of Death
        "live coral",             # BC All stars grow out 2025!!!
    ],
    "tag_denylist": [],
}

# Source title carries a double space ('grow out  2025'), faithful to the
# vendor's products.json verbatim. Centralized so a future single-space
# mistype on one of the four _by_title call sites doesn't fail with a
# diffuse 'fixture missing product titled' error.
BC_GROWOUT_TITLE = "BC All stars grow out  2025!!!"


def _load_fixture() -> list[dict]:
    with FIXTURE_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)["products"]


# CTK-039 pytest fixture wrapper — exposes the script-mode `_load_fixture()`
# return value as a pytest fixture so collected `def test_X(products)` test
# functions resolve cleanly under `pytest scrapers/tests/`. Script-mode
# invocation (`python -m scrapers.tests.test_battlecorals_parse`) continues
# to work via main()'s direct `_load_fixture()` call; the pytest decorator
# is metadata-only in that path.
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


def _normalize(p: dict) -> dict:
    return _normalize_product(p, BASE_URL, IMAGE_STRATEGY, ORIGINATOR_PREFIX)


# ─── Test 1: html_hash sentinel — sorted-keys-of-first-product SHA256 ─────────
def test_html_hash_first_product_keys(products):
    """Arch §2.6 Shopify variant: hash sorted key set of first product object.
    F5 fold (sort-before-hash) in parse_shopify.py — Shopify can change JSON
    key emission order across versions without a real schema change; sorting
    collapses ordering noise. Empirical anchor: 13 keys, matching PE+WWC+TSA+JF.
    """
    first = products[0]
    keys = sorted(first.keys())
    assert len(keys) == 13, (
        f"expected 13 keys on first product (matches PE+WWC+TSA+JF empirical "
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


# ─── Test 2: house lineage bare-TitleCase — no prefix synthesis at parse ──────
def test_house_lineage_normalize_no_prefix_synthesis(products):
    """Battlecorals house lineages (Hyperberry / Genie of Death / Joker 2.0)
    drop the "Battlecorals" prefix entirely. Parse-layer normalize_title
    preserves what the title says — "Hyperberry" stays "hyperberry" (no
    "battlecorals " injected). The matcher §3.4 stage 3 SYNTHESIZES
    "battlecorals " + normalized_title at match-time against canonical_index;
    that synthesis lives in matcher.py, not parse_shopify. This test pins
    the parse-layer contract: originator_prefix='battlecorals' YAML config
    does NOT affect normalize_title output (decision #23 + #18 interaction,
    mirroring test_jf_parse.test_no_prefix_coral_normalize_no_synthesis)."""
    p = _by_title(products, "Hyperberry")
    out = _normalize(p)
    assert out["raw_title"] == "Hyperberry"
    assert out["normalized_title"] == "hyperberry", (
        f"house lineage should normalize bare; got {out['normalized_title']!r}"
    )


# ─── Test 3: cross-vendor prefix — preserved (lowercased) ─────────────────────
def test_cross_vendor_prefix_lowercased_preserved(products):
    """Battlecorals propagates cross-vendor lineages with non-Battlecorals
    prefixes (TSA / ORA / WWC / AV / RR / LRO). These prefixes are PRESERVED
    in normalized_title (per decision #18 §3.2 cascade fix) so the matcher
    can hit canonical-exact / canonical-prefix at stages 1-2 directly.
    normalize_title lowercases so 'TSA Bill Murray' → 'tsa bill murray'."""
    tsa = _by_title(products, "TSA Bill Murray")
    ora = _by_title(products, "ORA Pearlberry")
    assert _normalize(tsa)["normalized_title"] == "tsa bill murray", (
        f"TSA prefix should preserve lowercase; got {_normalize(tsa)['normalized_title']!r}"
    )
    assert _normalize(ora)["normalized_title"] == "ora pearlberry", (
        f"ORA prefix should preserve lowercase; got {_normalize(ora)['normalized_title']!r}"
    )


# ─── Test 4: OOS product — variants.available all false → in_stock=False ──────
def test_oos_product_in_stock_false(products):
    """Genie of Death (Acropora Tenuis) is OOS at fixture-capture 2026-05-25.
    Between-drop window Battlecorals corals OOS state — any(v.available)
    correctly returns False when all variants are unavailable."""
    p = _by_title(products, "Genie of Death")
    out = _normalize(p)
    assert out["in_stock"] is False, f"expected in_stock=False, got {out['in_stock']!r}"


# ─── Test 5: in-stock product → in_stock=True ─────────────────────────────────
def test_in_stock_product_in_stock_true(products):
    """Hyperberry (Acropora Microclados) is in-stock at fixture-capture."""
    p = _by_title(products, "Hyperberry")
    out = _normalize(p)
    assert out["in_stock"] is True, f"expected in_stock=True, got {out['in_stock']!r}"


# ─── Test 6: Battlebox — empty product_type + null first-variant SKU ──────────
def test_battlebox_in_stock_with_null_sku(products):
    """2000.00 Battlebox Ships free is an empty-product_type coral grab-bag
    with null SKUs across all 8 variants. Validates the empty-bucket + null-
    SKU intersection: empty product_type passes filter (per Q-8 (a)), null
    SKUs across all variants → vendor_sku=None at the row level."""
    p = _by_title(products, "2000.00 Battlebox Ships free")
    out = _normalize(p)
    assert out["in_stock"] is True
    assert out["vendor_sku"] is None, (
        f"all-null-variant SKU should yield vendor_sku=None; got {out['vendor_sku']!r}"
    )


# ─── Test 7: first-SKU pick — empty-string variants fall through to None ──────
def test_first_sku_pick_falls_back_when_empty_string(products):
    """BC All stars grow out 2025!!! has 5 variants where the first carries
    sku='' (empty string, not null). parse_shopify._normalize_product's
    next((v['sku'] for v in variants if v['sku']), None) picks the first
    TRUTHY SKU — empty string falls through. All 5 variants here have empty
    SKUs, so vendor_sku=None at the row level. Validates the
    truthy-pick-not-not-null behavior."""
    p = _by_title(products, BC_GROWOUT_TITLE)
    out = _normalize(p)
    assert out["vendor_sku"] is None, (
        f"all-empty-string-SKU variants should yield vendor_sku=None (truthy "
        f"check, not is-not-None); got {out['vendor_sku']!r}"
    )


# ─── Test 8: first-SKU pick — picks first non-empty across variants ───────────
def test_first_sku_pick_picks_first_non_empty(products):
    """Hyperberry has 3 variants; first variant has sku='61345' (non-empty)
    — picker takes it directly. Standard first-SKU pick path."""
    p = _by_title(products, "Hyperberry")
    out = _normalize(p)
    assert out["vendor_sku"] == "61345", (
        f"first non-empty SKU should win; got {out['vendor_sku']!r}"
    )


# ─── Test 9: product_url is absolute (CTK-033 D1 anchor) ──────────────────────
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


# ─── Test 10: vendor_image_url is images[0].src (raw, pre-mirror) ─────────────
def test_vendor_image_url_first_image(products):
    """Phase B mirror queue pulls vendor_image_url and writes image_url after
    R2 storage. Parse layer just hands over the raw vendor URL untouched.
    Hyperberry has 3 images at fixture-capture."""
    p = _by_title(products, "Hyperberry")
    out = _normalize(p)
    expected_src = p["images"][0]["src"]
    assert out["vendor_image_url"] == expected_src, (
        f"vendor_image_url should be images[0].src; expected {expected_src!r}, "
        f"got {out['vendor_image_url']!r}"
    )


# ─── Test 11: currency = USD per Q1-3 lock ────────────────────────────────────
def test_currency_usd_default(products):
    """Phase 1+2 vendors all USD per Q1-3 (arch §1.4 / decision register).
    Parse layer hardcodes USD; currency-aware logic re-opens at Phase 2 if
    any vendor ships non-USD."""
    for p in products:
        out = _normalize(p)
        assert out["currency"] == "USD", (
            f"currency drift on {p['title']!r}: expected 'USD', got {out['currency']!r}"
        )


# ─── Test 12: lineage_flag — cross-vendor ALL-CAPS prefix fires 'vendor-named' ─
def test_lineage_flag_cross_vendor_prefix_vendor_named(products):
    """Battlecorals' cross-vendor propagation surfaces in lineage_flag: 2-4
    char ALL-CAPS prefix + title-case word triggers infer_lineage_flag's
    regex. TSA / ORA / BC titles fire 'vendor-named'. Distinct from JF's
    ALL-CAPS-throughout shape where no title ever fires."""
    tsa = _by_title(products, "TSA Bill Murray")
    ora = _by_title(products, "ORA Pearlberry")
    bc_outlier = _by_title(products, BC_GROWOUT_TITLE)
    bc_merch = _by_title(products, "BC Tee Shirt")
    assert _normalize(tsa)["lineage_flag"] == "vendor-named"
    assert _normalize(ora)["lineage_flag"] == "vendor-named"
    assert _normalize(bc_outlier)["lineage_flag"] == "vendor-named"
    assert _normalize(bc_merch)["lineage_flag"] == "vendor-named"


# ─── Test 13: lineage_flag — bare TitleCase stays 'unknown' ───────────────────
def test_lineage_flag_bare_titlecase_stays_unknown(products):
    """Battlecorals house lineages are bare TitleCase ("Hyperberry", "Genie
    of Death", "Love SKY"). infer_lineage_flag's regex requires ALL-CAPS-
    prefix THEN title-case — bare TitleCase titles miss. Matcher §3.4 stage 3
    originator_prefix='battlecorals' synthesis is the real lineage-capture
    mechanism for house pieces.

    Note: 'Love SKY' has 'SKY' all-caps at the suffix but no all-caps prefix
    at the start — regex anchors at ^, so it doesn't fire."""
    hyperberry = _by_title(products, "Hyperberry")
    genie = _by_title(products, "Genie of Death")
    love_sky = _by_title(products, "Love SKY")
    battlebox = _by_title(products, "2000.00 Battlebox Ships free")
    assert _normalize(hyperberry)["lineage_flag"] == "unknown"
    assert _normalize(genie)["lineage_flag"] == "unknown"
    assert _normalize(love_sky)["lineage_flag"] == "unknown"
    assert _normalize(battlebox)["lineage_flag"] == "unknown"


# ─── Test 14: category inference — Acropora-genus product_type → 'sps' ────────
def test_category_inference(products):
    """infer_category matches against product_type + tags + title. Arch §1.4
    enum: ('sps','lps','softie','zoa','mushroom','anemone','clam','chalice',
    'fish','invert','equipment','other'). Battlecorals taxonomic-granularity
    product_type carries the signal: 'Acropora Microclados' / 'Acropora sp.'
    / 'Acropora' / 'Acropora Tenuis' all match \\bacropora\\b → 'sps'. Empty
    product_type + non-Acropora-bearing titles (Battlebox, BC Tee Shirt, BC
    All stars grow out — 'live coral' product_type) fall through to None
    — accurate parse-layer reflection of current shape."""
    hyperberry = _by_title(products, "Hyperberry")                   # Acropora Microclados
    tsa_bill = _by_title(products, "TSA Bill Murray")                # Acropora sp.
    ora = _by_title(products, "ORA Pearlberry")                      # Acropora
    genie = _by_title(products, "Genie of Death")                    # Acropora Tenuis
    love_sky = _by_title(products, "Love SKY")                       # Acropora sp
    bc_outlier = _by_title(products, BC_GROWOUT_TITLE)  # live coral
    battlebox = _by_title(products, "2000.00 Battlebox Ships free")  # ""
    bc_merch = _by_title(products, "BC Tee Shirt")                   # ""

    assert _normalize(hyperberry)["category"] == "sps"
    assert _normalize(tsa_bill)["category"] == "sps"
    assert _normalize(ora)["category"] == "sps"
    assert _normalize(genie)["category"] == "sps"
    assert _normalize(love_sky)["category"] == "sps"
    # 'live coral' product_type doesn't match any specific category pattern;
    # title 'BC All stars grow out 2025!!!' carries no coral-genus signal either.
    assert _normalize(bc_outlier)["category"] is None
    # Battlebox + BC Tee Shirt: empty product_type, no category-matching title.
    assert _normalize(battlebox)["category"] is None
    assert _normalize(bc_merch)["category"] is None


# ─── Test 15 (CTK-037): filter keeps house lineage Acropora Microclados ───────
def test_filter_keeps_house_lineage_acropora_microclados(products):
    """Hyperberry has product_type='Acropora Microclados' — in allowlist,
    empty tag_denylist = KEEP. Anchor case for Battlecorals house bare-
    TitleCase coral named via seed-list canonical."""
    p = _by_title(products, "Hyperberry")
    assert _should_keep(p, BC_CATEGORY_FILTER) is True


# ─── Test 16 (CTK-037): filter keeps cross-vendor Acropora sp. ────────────────
def test_filter_keeps_cross_vendor_acropora_sp_dot(products):
    """TSA Bill Murray (cross-vendor propagated) has product_type='Acropora
    sp.' — in allowlist = KEEP. Anchor case for the 137-item Acropora sp.
    dominant bucket."""
    p = _by_title(products, "TSA Bill Murray")
    assert _should_keep(p, BC_CATEGORY_FILTER) is True


# ─── Test 17 (CTK-037): filter keeps period-less Acropora sp variant ──────────
def test_filter_keeps_period_less_acropora_sp_variant(products):
    """Love SKY has product_type='Acropora sp' (no period — 6-item variant
    bucket distinct from 'Acropora sp.' 137-item bucket). Both shapes
    enumerated as separate allowlist entries per CTK-037 exact-string
    convention. Period-less variant survives."""
    p = _by_title(products, "Love SKY")
    assert _should_keep(p, BC_CATEGORY_FILTER) is True


# ─── Test 18 (CTK-037): filter keeps Acropora Tenuis OOS ──────────────────────
def test_filter_keeps_acropora_tenuis_oos(products):
    """Genie of Death has product_type='Acropora Tenuis' — in allowlist =
    KEEP. Filter is in_stock-agnostic at parse layer; persist phase handles
    OOS state via in_stock=False on the vendor_listings row."""
    p = _by_title(products, "Genie of Death")
    assert _should_keep(p, BC_CATEGORY_FILTER) is True


# ─── Test 19 (CTK-037): filter keeps 'live coral' product_type grow-out ───────
def test_filter_keeps_live_coral_growout(products):
    """BC All stars grow out 2025!!! has product_type='live coral' — in
    allowlist = KEEP. 'live coral' bucket carries 4 grow-out announcement
    entries on Battlecorals' catalog."""
    p = _by_title(products, BC_GROWOUT_TITLE)
    assert _should_keep(p, BC_CATEGORY_FILTER) is True


# ─── Test 20 (CTK-037 Session 5 Q-8 (a)): empty-product_type Battlebox keeps ──
def test_filter_keeps_empty_product_type_battlebox(products):
    """Battlecorals' empty-product_type bucket carries 121 items (24% of
    catalog) at 2026-05-25 walk — mostly real coral content (Battlebox
    coral grab-bags + named house lineages + grow-out entries). "" in
    allowlist per CTK-027 Session 5 Q-8 path (a) recovers these rows."""
    p = _by_title(products, "2000.00 Battlebox Ships free")
    assert _should_keep(p, BC_CATEGORY_FILTER) is True


# ─── Test 21 (CTK-037 Session 5 Q-8 (a)): empty-product_type merch leak ───────
def test_filter_keeps_empty_product_type_merch_leak(products):
    """BC Tee Shirt also lands in the empty-product_type bucket — it
    PASSES the "" allowlist entry. This is acceptable parse-layer
    permissiveness per CTK-027 Session 5 Q-8 path (a) precedent: frontend
    has_image filter is the load-bearing downstream gate (most merch leaks
    lack coral-quality images). Distinct from JF's 'tshirt' product_type
    pattern which IS rejected by allowlist directly — Battlecorals merch
    falls into the same empty bucket as the coral grab-bags, so allowlist-
    side rejection isn't structurally possible without removing "" entirely
    (which would lose 100+ real coral rows)."""
    p = _by_title(products, "BC Tee Shirt")
    assert _should_keep(p, BC_CATEGORY_FILTER) is True


# ─── Test 22 (CTK-037): permissive default when no category_filter block ──────
def test_filter_battlecorals_permissive_when_no_block(products):
    """Phase 2 vendor onboarding inheritance — None or {} = no gate. Every
    fixture product passes."""
    for p in products:
        assert _should_keep(p, None) is True
        assert _should_keep(p, {}) is True


# ─── Test 23 (CTK-037): kept count across Battlecorals fixture matches ────────
def test_filter_battlecorals_kept_count_matches(products):
    """Fixture composition: Hyperberry (Acropora Microclados) + TSA Bill
    Murray (Acropora sp.) + ORA Pearlberry (Acropora) + BC All stars
    (live coral) + Genie of Death (Acropora Tenuis) + 2000.00 Battlebox
    (empty) + Love SKY (Acropora sp) + BC Tee Shirt (empty) = 8 kept, 0
    skipped under BC_CATEGORY_FILTER. Pins fixture composition + filter
    behavior; if a fixture entry is added/removed the count line documents
    the intent."""
    kept = sum(1 for p in products if _should_keep(p, BC_CATEGORY_FILTER))
    skipped = sum(1 for p in products if not _should_keep(p, BC_CATEGORY_FILTER))
    assert kept == 8, f"expected 8 kept, got {kept}"
    assert skipped == 0, (
        f"expected 0 skipped (Battlecorals' 2026-05-25 walk had ZERO non-coral "
        f"product_types observed; no allowlist-miss in fixture); got {skipped}"
    )


# ─── Test 24 (CTK-037 Session 5.5): predicate normalization keeps None/absent ─
def test_filter_normalizes_none_product_type_to_empty_string(products):
    """CTK-037 Session 5.5 — None or key-absent product_type normalizes to ""
    so Battlecorals empty-string allowlist entry matches both Shopify shape
    variants. Prevents silent recall regression if Shopify shifts empty-
    bucket representation. Mirror of test_jf_parse + test_tsa_parse
    precedent."""
    product_none = {"product_type": None, "title": "Some coral", "tags": []}
    product_missing = {"title": "Some coral", "tags": []}  # key absent
    cf = BC_CATEGORY_FILTER  # has "" in allowlist
    assert _should_keep(product_none, cf) is True
    assert _should_keep(product_missing, cf) is True


# ─── Test 25 (CTK-037 Session 5.5): normalization is symmetric (rejects too) ──
def test_filter_rejects_none_product_type_when_empty_not_in_allowlist(products):
    """CTK-037 Session 5.5 — normalization is symmetric; None still rejects
    when "" is not in the allowlist. Mirror of the JF + TSA precedent tests."""
    product = {"product_type": None, "title": "Some coral", "tags": []}
    cf = {"product_type_allowlist": ["Acropora sp."], "tag_denylist": []}
    assert _should_keep(product, cf) is False


def main() -> int:
    products = _load_fixture()
    print(f"loaded fixture: {len(products)} products from {FIXTURE_PATH}")

    tests = [
        test_html_hash_first_product_keys,
        test_house_lineage_normalize_no_prefix_synthesis,
        test_cross_vendor_prefix_lowercased_preserved,
        test_oos_product_in_stock_false,
        test_in_stock_product_in_stock_true,
        test_battlebox_in_stock_with_null_sku,
        test_first_sku_pick_falls_back_when_empty_string,
        test_first_sku_pick_picks_first_non_empty,
        test_product_url_absolute,
        test_vendor_image_url_first_image,
        test_currency_usd_default,
        test_lineage_flag_cross_vendor_prefix_vendor_named,
        test_lineage_flag_bare_titlecase_stays_unknown,
        test_category_inference,
        test_filter_keeps_house_lineage_acropora_microclados,
        test_filter_keeps_cross_vendor_acropora_sp_dot,
        test_filter_keeps_period_less_acropora_sp_variant,
        test_filter_keeps_acropora_tenuis_oos,
        test_filter_keeps_live_coral_growout,
        test_filter_keeps_empty_product_type_battlebox,
        test_filter_keeps_empty_product_type_merch_leak,
        test_filter_battlecorals_permissive_when_no_block,
        test_filter_battlecorals_kept_count_matches,
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
