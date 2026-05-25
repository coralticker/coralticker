"""scrapers/tests/test_unique_corals_parse.py — CTK-085 parse-layer tests for
Unique Corals' Shopify /products.json shape against locked fixture
scrapers/tests/fixtures/unique_corals/products.sample.json.

Parse-only — no DB, no network. Validates parse_shopify._normalize_product
output shape + html_hash sentinel computation across eight curated UC
products covering: UC abbreviation prefix in CORAL bucket (UC Burnt Orange
OG Jawbreaker-WYSIWYG — seed-list canonical lineage); UC full-word prefix
in empty-PT bucket (Unique Corals Rainbow Hyacinthus — dual-prefix shape
demonstration); bare-WYSIWYG empty-PT (Strawberry Shortcake Colony 2.5
-WYSIWYG — OOS case); cross-vendor TSA empty-PT (TSA Bill Murray Acropora-
WYSIWYG); cross-vendor WWC empty-PT (WWC Grafted Firewalker Montipora-
WYSIWYG); UC abbreviation OOS in CORAL (UC Mystic Montipora-WYSIWYG —
in_stock=False on CORAL allowlist hit); equipment leak in empty-PT via
tag_denylist (PNS Deep Cycle (16 oz) — 'goods' + 'PNS' tags trigger
rejection); Drygoods PT-allowlist-miss (Activated Carbon 1000ml).

Coverage parity with test_battlecorals_parse.py (CTK-085 Session 2
precedent) with UC-specific shape adjustments: tag_denylist is materially
exercised (Battlecorals' was empty), so REJECT-path coverage spans both
PT-allowlist-miss + tag-denylist-hit dimensions; lineage_flag fires on the
'UC X' abbreviation (2-char ALL-CAPS prefix matches infer_lineage_flag
regex) but NOT on the 'Unique Corals X' full-word ('Unique' is 6-char
TitleCase, regex misses), demonstrating UC's dual-prefix split at parse
layer; PNS Deep Cycle equipment item fires lineage_flag='vendor-named' at
parse but rejects downstream via tag_denylist (orthogonal-axis demonstration).

Runnable as:
  python -m scrapers.tests.test_unique_corals_parse

Fixture regen path documented in scrapers/vendors/unique_corals.py docstring
(CTK-024/025/026/027/Battlecorals convention).

Coverage:
  test_html_hash_first_product_keys                        arch §2.6 sentinel (13 keys)
  test_house_lineage_normalize_no_prefix_synthesis         Strawberry Shortcake bare-TitleCase
  test_uc_abbreviation_prefix_lowercased_preserved         UC X → uc x
  test_uc_full_word_prefix_lowercased_preserved            Unique Corals X → unique corals x
  test_cross_vendor_prefix_lowercased_preserved            TSA / WWC prefixes preserved
  test_oos_product_in_stock_false                          UC Mystic Montipora OOS
  test_in_stock_product_in_stock_true                      UC Burnt Orange in-stock
  test_first_sku_pick_non_empty                            Rainbow Hyacinthus first-truthy-SKU
  test_product_url_absolute                                CTK-033 D1 anchor
  test_vendor_image_url_first_image                        Rainbow Hyacinthus 3-image multi-image
  test_currency_usd_default                                Q1-3 lock
  test_lineage_flag_uc_abbreviation_fires_vendor_named     UC X fires regex
  test_lineage_flag_uc_full_word_stays_unknown             Unique Corals X misses regex (TitleCase)
  test_lineage_flag_cross_vendor_prefix_fires_vendor_named TSA / WWC fire regex
  test_lineage_flag_bare_titlecase_stays_unknown           Strawberry Shortcake misses regex
  test_lineage_flag_pns_equipment_fires_but_filtered       PNS fires regex; filter rejects downstream
  test_category_inference                                  per-fixture tag-based infer_category
  test_filter_keeps_coral_pt_uc_abbreviation               UC Burnt Orange CORAL bucket
  test_filter_keeps_coral_pt_oos_uc_mystic                 UC Mystic OOS but CORAL hit
  test_filter_keeps_empty_pt_uc_full_word                  Unique Corals Rainbow Hyacinthus empty-PT
  test_filter_keeps_empty_pt_bare_titlecase                Strawberry Shortcake empty-PT OOS
  test_filter_keeps_empty_pt_cross_vendor_tsa              TSA Bill Murray empty-PT
  test_filter_keeps_empty_pt_cross_vendor_wwc              WWC Grafted Firewalker empty-PT
  test_filter_rejects_empty_pt_pns_via_tag_denylist        PNS Deep Cycle (empty PT + 'goods' + 'PNS')
  test_filter_rejects_drygoods_pt_allowlist_miss           Activated Carbon Drygoods PT
  test_filter_unique_corals_permissive_when_no_block       Phase 2 inheritance
  test_filter_unique_corals_kept_count_matches             6 kept / 2 skipped under slim allowlist
  test_filter_normalizes_none_product_type_to_empty_string CTK-037 Session 5.5
  test_filter_rejects_none_product_type_when_empty_not_in_allowlist  symmetric
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

from scrapers.common.parse_shopify import _normalize_product, _should_keep


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "unique_corals" / "products.sample.json"
BASE_URL = "https://uniquecorals.com"
ORIGINATOR_PREFIX = "uc"  # matches scrapers/vendors/unique_corals.yaml D1 lock
IMAGE_STRATEGY = "mirror"

# Slim filter mirroring the 8-fixture surface. Production allowlist at
# scrapers/vendors/unique_corals.yaml carries 3 PT entries (CORAL / Coral /
# "") + 10 tag_denylist entries; slim filter pins the same shape against the
# fixture's actual PTs ("CORAL" / "" / "Drygoods") + the two tag_denylist
# entries the fixture exercises ('goods' + 'PNS'). Keeping the slim version
# in sync with the production YAML on every category amendment would create
# drift risk; tests pin filter BEHAVIOR on the fixture-exercised paths.
UC_CATEGORY_FILTER = {
    "product_type_allowlist": [
        "",          # empty-PT bucket (Strawberry Shortcake / TSA Bill Murray / WWC Grafted Firewalker / Unique Corals Rainbow Hyacinthus / PNS Deep Cycle)
        "CORAL",     # UC Burnt Orange OG Jawbreaker / UC Mystic Montipora
    ],
    "tag_denylist": [
        "goods",     # universal dry-goods signal; PNS Deep Cycle co-tagged
        "PNS",       # PNS supplements brand
    ],
}


def _load_fixture() -> list[dict]:
    with FIXTURE_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)["products"]


# CTK-039 pytest fixture wrapper — exposes the script-mode `_load_fixture()`
# return value as a pytest fixture so collected `def test_X(products)` test
# functions resolve cleanly under `pytest scrapers/tests/`. Script-mode
# invocation (`python -m scrapers.tests.test_unique_corals_parse`) continues
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
    collapses ordering noise. Empirical anchor: 13 keys, matching
    PE+WWC+TSA+JF+Battlecorals."""
    first = products[0]
    keys = sorted(first.keys())
    assert len(keys) == 13, (
        f"expected 13 keys on first product (matches PE+WWC+TSA+JF+Battlecorals "
        f"empirical anchor), got {len(keys)}: {keys}"
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


# ─── Test 2: bare-TitleCase normalize — no synthesis at parse layer ───────────
def test_house_lineage_normalize_no_prefix_synthesis(products):
    """UC bare-TitleCase house lineages (Strawberry Shortcake Colony, similar
    WYSIWYG frags) drop the vendor prefix entirely. Parse-layer normalize_title
    preserves what the title says — "Strawberry Shortcake Colony 2.5 -WYSIWYG"
    stays "strawberry shortcake colony 2.5 -wysiwyg" (no "uc " injected). The
    matcher §3.4 stage 3 SYNTHESIZES "uc " + normalized_title at match-time
    against canonical_index; that synthesis lives in matcher.py, not
    parse_shopify. This test pins the parse-layer contract:
    originator_prefix='uc' YAML config does NOT affect normalize_title
    output (decision #23 + #18 interaction, mirroring
    test_battlecorals_parse.test_house_lineage_normalize_no_prefix_synthesis)."""
    p = _by_title(products, "Strawberry Shortcake Colony 2.5 -WYSIWYG")
    out = _normalize(p)
    assert out["raw_title"] == "Strawberry Shortcake Colony 2.5 -WYSIWYG"
    # normalize_title also strips the 'WYSIWYG' suffix marker (framework
    # behavior in normalize.py — WYSIWYG is a vendor-side photo-disclosure
    # tag, not part of the lineage name); " -WYSIWYG" with leading-space-
    # hyphen gets fully removed. UC's '-WYSIWYG' (no leading space) leaves
    # the hyphen dangling — distinct shape demonstrated in Test 3.
    assert out["normalized_title"] == "strawberry shortcake colony 2.5", (
        f"bare-TitleCase house lineage should normalize bare with "
        f"WYSIWYG suffix stripped; got {out['normalized_title']!r}"
    )


# ─── Test 3: UC abbreviation prefix lowercased and preserved ──────────────────
def test_uc_abbreviation_prefix_lowercased_preserved(products):
    """UC catalog carries the 'UC X' abbreviation self-prefix shape (49 / 524
    = 9.3% of catalog at 2026-05-25 walk). normalize_title lowercases — 'UC
    Burnt Orange OG Jawbreaker-WYSIWYG' → 'uc burnt orange og jawbreaker-
    wysiwyg'. Matcher §3.4 stage 1 hits canonical_index directly for seed-
    list canonical 'UC Burnt Orange OG Jawbreaker' (normalized 'uc burnt
    orange og jawbreaker') via prefix-bounded match. No stage 3 synthesis
    needed for this case — abbreviation form aligns with seed-list."""
    p = _by_title(products, "UC Burnt Orange OG Jawbreaker-WYSIWYG")
    out = _normalize(p)
    # normalize_title strips 'WYSIWYG' suffix marker; '-WYSIWYG' (no leading
    # space) leaves the dangling hyphen — distinct from Strawberry Shortcake
    # case (Test 2) which had ' -WYSIWYG' with leading space-hyphen fully
    # removed. UC's WYSIWYG-suffix convention varies by title (sometimes
    # space-hyphen, sometimes hyphen-only); normalize_title pinning here.
    assert out["normalized_title"] == "uc burnt orange og jawbreaker-", (
        f"UC abbreviation prefix should lowercase + preserve with WYSIWYG "
        f"stripped; got {out['normalized_title']!r}"
    )


# ─── Test 4: UC full-word prefix lowercased and preserved ─────────────────────
def test_uc_full_word_prefix_lowercased_preserved(products):
    """UC catalog also carries 'Unique Corals X' full-word self-prefix shape
    (80 / 524 = 15.3% at 2026-05-25 walk) — dual-prefix structure distinct
    from all prior Phase 1+2 vendors. normalize_title lowercases — 'Unique
    Corals Rainbow Hyacinthus' → 'unique corals rainbow hyacinthus'.
    Matcher §3.4 dual-shape matcher limitation: this full-word variant does
    NOT synthesize cleanly against seed-list 'UC X' canonicals via stage 3
    alone (synthesis adds 'uc ' + normalized_title; stripping 'unique corals'
    requires stage 2 vendor-prefix awareness). Flagged in unique_corals.py
    docstring (D) finding + CTK-085 Session 3 Q-1 for /lead-architect."""
    p = _by_title(products, "Unique Corals Rainbow Hyacinthus")
    out = _normalize(p)
    assert out["normalized_title"] == "unique corals rainbow hyacinthus", (
        f"UC full-word prefix should lowercase + preserve; got "
        f"{out['normalized_title']!r}"
    )


# ─── Test 5: cross-vendor prefix — preserved (lowercased) ─────────────────────
def test_cross_vendor_prefix_lowercased_preserved(products):
    """UC catalog propagates cross-vendor lineages with non-UC prefixes
    (ARID 10, WWC 8, JF 6, TSA 6, ECM 5, PC 2, PNS 2). These prefixes are
    PRESERVED in normalized_title (per decision #18 §3.2 cascade fix) so
    the matcher can hit canonical-exact / canonical-prefix at stages 1-2
    directly. normalize_title lowercases so 'TSA Bill Murray Acropora-
    WYSIWYG' → 'tsa bill murray acropora-wysiwyg'."""
    tsa = _by_title(products, "TSA Bill Murray Acropora-WYSIWYG")
    wwc = _by_title(products, "WWC Grafted Firewalker Montipora-WYSIWYG")
    # WYSIWYG suffix stripped per Test 2 + Test 3 documented framework
    # behavior; cross-vendor prefixes (TSA / WWC) preserved at front.
    assert _normalize(tsa)["normalized_title"] == "tsa bill murray acropora-", (
        f"TSA prefix should preserve lowercase (WYSIWYG stripped); got "
        f"{_normalize(tsa)['normalized_title']!r}"
    )
    assert _normalize(wwc)["normalized_title"] == "wwc grafted firewalker montipora-", (
        f"WWC prefix should preserve lowercase (WYSIWYG stripped); got "
        f"{_normalize(wwc)['normalized_title']!r}"
    )


# ─── Test 6: OOS product — variants.available all false → in_stock=False ──────
def test_oos_product_in_stock_false(products):
    """UC Mystic Montipora-WYSIWYG (CORAL bucket SPS) is OOS at fixture-
    capture 2026-05-25. Between-drop window UC corals OOS state — any(
    v.available) correctly returns False when all variants are unavailable.
    Distinct shape from Battlecorals Genie of Death OOS — UC Mystic is in
    CORAL allowlist (in_stock-agnostic filter pass) so it still surfaces
    on vendor_listings rows; in_stock=False marks it for OOS rendering."""
    p = _by_title(products, "UC Mystic Montipora-WYSIWYG")
    out = _normalize(p)
    assert out["in_stock"] is False, f"expected in_stock=False, got {out['in_stock']!r}"


# ─── Test 7: in-stock product → in_stock=True ─────────────────────────────────
def test_in_stock_product_in_stock_true(products):
    """UC Burnt Orange OG Jawbreaker-WYSIWYG (CORAL bucket, seed-list
    canonical) is in-stock at fixture-capture 2026-05-25."""
    p = _by_title(products, "UC Burnt Orange OG Jawbreaker-WYSIWYG")
    out = _normalize(p)
    assert out["in_stock"] is True, f"expected in_stock=True, got {out['in_stock']!r}"


# ─── Test 8: first-SKU pick — picks first non-empty across variants ───────────
def test_first_sku_pick_non_empty(products):
    """Unique Corals Rainbow Hyacinthus has 1 variant with sku='Frag to
    Order' (non-empty). parse_shopify._normalize_product's
    next((v['sku'] for v in variants if v['sku']), None) picks the first
    truthy SKU. UC's SKU shape varies (date-stamped like '5-22-26',
    descriptive like 'Frag to Order', or compact like 'PNS-DC') — pin
    handler shape, not specific values."""
    p = _by_title(products, "Unique Corals Rainbow Hyacinthus")
    out = _normalize(p)
    assert out["vendor_sku"] == "Frag to Order", (
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
            f"product_url missing handle suffix for {p['title']!r}: "
            f"{out['product_url']!r}"
        )


# ─── Test 10: vendor_image_url is images[0].src (raw, pre-mirror) ─────────────
def test_vendor_image_url_first_image(products):
    """Phase B mirror queue pulls vendor_image_url and writes image_url
    after R2 storage. Parse layer just hands over the raw vendor URL
    untouched. Unique Corals Rainbow Hyacinthus has 3 images at fixture-
    capture — multi-image case demonstrates that the picker correctly
    extracts the [0].src position even when multiple images exist."""
    p = _by_title(products, "Unique Corals Rainbow Hyacinthus")
    out = _normalize(p)
    expected_src = p["images"][0]["src"]
    assert out["vendor_image_url"] == expected_src, (
        f"vendor_image_url should be images[0].src; expected {expected_src!r}, "
        f"got {out['vendor_image_url']!r}"
    )


# ─── Test 11: currency = USD per Q1-3 lock ────────────────────────────────────
def test_currency_usd_default(products):
    """Phase 1+2 vendors all USD per Q1-3 (arch §1.4 / decision register).
    Parse layer hardcodes USD; currency-aware logic re-opens at Phase 2+ if
    any vendor ships non-USD."""
    for p in products:
        out = _normalize(p)
        assert out["currency"] == "USD", (
            f"currency drift on {p['title']!r}: expected 'USD', got "
            f"{out['currency']!r}"
        )


# ─── Test 12: lineage_flag — UC abbreviation prefix fires 'vendor-named' ──────
def test_lineage_flag_uc_abbreviation_fires_vendor_named(products):
    """UC's 'UC X' abbreviation prefix (2-char ALL-CAPS) fires
    infer_lineage_flag's regex — same shape as Battlecorals' cross-vendor
    propagation (TSA / ORA / BC fires). Fires on UC Burnt Orange OG
    Jawbreaker-WYSIWYG + UC Mystic Montipora-WYSIWYG."""
    burnt = _by_title(products, "UC Burnt Orange OG Jawbreaker-WYSIWYG")
    mystic = _by_title(products, "UC Mystic Montipora-WYSIWYG")
    assert _normalize(burnt)["lineage_flag"] == "vendor-named"
    assert _normalize(mystic)["lineage_flag"] == "vendor-named"


# ─── Test 13: lineage_flag — UC full-word prefix stays 'unknown' ──────────────
def test_lineage_flag_uc_full_word_stays_unknown(products):
    """UC's 'Unique Corals X' full-word self-prefix shape does NOT fire
    infer_lineage_flag's regex — 'Unique' is 6-char TitleCase, not the
    2-4 char ALL-CAPS-prefix shape the regex anchors on. UC is the first
    vendor where self-prefix-bearing rate is non-zero but lineage_flag
    fires at different rates for the two prefix shapes (15.3% full-word
    + 9.3% abbreviation = 24.6% combined self-prefix; ~9.3% fires
    'vendor-named', ~15.3% lands 'unknown'). Documented in unique_corals.py
    docstring (D) finding."""
    p = _by_title(products, "Unique Corals Rainbow Hyacinthus")
    out = _normalize(p)
    assert out["lineage_flag"] == "unknown", (
        f"'Unique Corals X' full-word self-prefix should land 'unknown'; "
        f"got {out['lineage_flag']!r}"
    )


# ─── Test 14: lineage_flag — cross-vendor ALL-CAPS prefix fires ───────────────
def test_lineage_flag_cross_vendor_prefix_fires_vendor_named(products):
    """UC's cross-vendor propagation surfaces in lineage_flag: 2-4 char
    ALL-CAPS prefix + title-case word triggers infer_lineage_flag's
    regex. TSA / WWC titles fire 'vendor-named'. Same shape as Battlecorals
    cross-vendor TSA / ORA / BC propagation."""
    tsa = _by_title(products, "TSA Bill Murray Acropora-WYSIWYG")
    wwc = _by_title(products, "WWC Grafted Firewalker Montipora-WYSIWYG")
    assert _normalize(tsa)["lineage_flag"] == "vendor-named"
    assert _normalize(wwc)["lineage_flag"] == "vendor-named"


# ─── Test 15: lineage_flag — bare TitleCase stays 'unknown' ───────────────────
def test_lineage_flag_bare_titlecase_stays_unknown(products):
    """UC house bare-TitleCase WYSIWYG frags (no vendor prefix) miss
    infer_lineage_flag's regex — regex requires 2-4 char ALL-CAPS prefix
    THEN title-case. 'Strawberry Shortcake Colony 2.5 -WYSIWYG' is bare
    TitleCase + numeric/punct suffix. Matcher §3.4 stage 3 originator_prefix='uc'
    synthesis is the real lineage-capture mechanism for house pieces."""
    p = _by_title(products, "Strawberry Shortcake Colony 2.5 -WYSIWYG")
    out = _normalize(p)
    assert out["lineage_flag"] == "unknown", (
        f"bare TitleCase house lineage should land 'unknown'; got "
        f"{out['lineage_flag']!r}"
    )


# ─── Test 16: lineage_flag — PNS equipment fires but filtered downstream ──────
def test_lineage_flag_pns_equipment_fires_but_filtered(products):
    """PNS Deep Cycle (16 oz) is an equipment item (supplements brand) —
    but its 3-char ALL-CAPS 'PNS' prefix fires infer_lineage_flag's regex
    at parse layer. lineage_flag='vendor-named' lands on the row regardless
    of actual coral status. The filter rejection happens DOWNSTREAM via
    tag_denylist ('goods' + 'PNS' tags trigger _should_keep=False) — parse-
    layer lineage_flag classification is orthogonal to filter-layer
    keep/reject. This test pins both the orthogonality + the equipment-leak
    discipline (rejection is at filter, not at lineage_flag)."""
    p = _by_title(products, "PNS Deep Cycle (16 oz)")
    out = _normalize(p)
    assert out["lineage_flag"] == "vendor-named", (
        f"PNS ALL-CAPS prefix fires regex regardless of coral-status; got "
        f"{out['lineage_flag']!r}"
    )
    # Filter-layer rejection: tag_denylist closes the gap (see Test 24)


# ─── Test 17: category inference — per-fixture tag-based pinning ──────────────
def test_category_inference(products):
    """infer_category matches against product_type + tags + title. Arch §1.4
    enum: ('sps','lps','softie','zoa','mushroom','anemone','clam','chalice',
    'fish','invert','equipment','other'). UC's structural-class product_type
    ('CORAL' / '' / 'Drygoods') provides less direct signal than Battlecorals'
    taxonomic-genus shape — tags are the primary category-inference axis here
    ('sps' tag → 'sps'; 'softy' tag → 'softie' via softy/softie alias;
    'Acropora' / 'monti' / 'montipora' tags → 'sps'; equipment tags fall
    through to None).

    Per-fixture pin (full 8 product coverage):"""
    pins = {
        "UC Burnt Orange OG Jawbreaker-WYSIWYG":      "softie",   # 'softy' tag
        "Unique Corals Rainbow Hyacinthus":            "sps",      # 'sps'+'Acropora' tags
        "Strawberry Shortcake Colony 2.5 -WYSIWYG":   "sps",      # 'sps'+'Acropora' tags
        "TSA Bill Murray Acropora-WYSIWYG":            "sps",      # 'sps'+'Acropora' tags
        "WWC Grafted Firewalker Montipora-WYSIWYG":   "sps",      # 'sps'+'montipora' tags
        "UC Mystic Montipora-WYSIWYG":                 "sps",      # 'sps' tag
        "PNS Deep Cycle (16 oz)":                      None,        # 'goods'+'PNS'; no coral category
        "Activated Carbon 1000ml":                     None,        # 'goods'+'triton'; no coral category
    }
    for title, expected in pins.items():
        p = _by_title(products, title)
        out = _normalize(p)
        assert out["category"] == expected, (
            f"category mismatch for {title!r}: expected {expected!r}, got "
            f"{out['category']!r} (tags={p.get('tags')})"
        )


# ─── Test 18 (CTK-037): filter keeps UC Burnt Orange in CORAL bucket ──────────
def test_filter_keeps_coral_pt_uc_abbreviation(products):
    """UC Burnt Orange OG Jawbreaker has product_type='CORAL' — in
    allowlist, no denylisted tags ('beginners' / 'coral' / 'just frags!' /
    'softy' / 'WYSIWYG' — none in denylist) = KEEP. Anchor case for UC
    abbreviation prefix + CORAL bucket allowlist hit + seed-list canonical
    'UC Burnt Orange OG Jawbreaker'."""
    p = _by_title(products, "UC Burnt Orange OG Jawbreaker-WYSIWYG")
    assert _should_keep(p, UC_CATEGORY_FILTER) is True


# ─── Test 19 (CTK-037): filter keeps UC Mystic Montipora OOS in CORAL ─────────
def test_filter_keeps_coral_pt_oos_uc_mystic(products):
    """UC Mystic Montipora-WYSIWYG has product_type='CORAL' + in_stock=False
    — filter is in_stock-agnostic at parse layer; persist phase handles
    OOS state via in_stock=False on the vendor_listings row. KEEP confirmed."""
    p = _by_title(products, "UC Mystic Montipora-WYSIWYG")
    assert _should_keep(p, UC_CATEGORY_FILTER) is True


# ─── Test 20 (CTK-037 Q-8 (a)): empty-PT UC full-word keeps ───────────────────
def test_filter_keeps_empty_pt_uc_full_word(products):
    """Unique Corals Rainbow Hyacinthus has product_type='' — "" in
    allowlist per CTK-027 Session 5 Q-8 path (a) precedent. Tags 'acro' /
    'Acropora' / 'sps' / 'UC signature' — none in denylist = KEEP.
    Recovers UC full-word self-prefix WYSIWYG signature frag."""
    p = _by_title(products, "Unique Corals Rainbow Hyacinthus")
    assert _should_keep(p, UC_CATEGORY_FILTER) is True


# ─── Test 21 (CTK-037 Q-8 (a)): empty-PT bare-TitleCase WYSIWYG keeps ─────────
def test_filter_keeps_empty_pt_bare_titlecase(products):
    """Strawberry Shortcake Colony 2.5 -WYSIWYG has product_type='' +
    in_stock=False — both axes pass: "" in allowlist (Q-8 (a)) and
    in_stock-agnostic filter. Tags 'acro' / 'Acropora' / 'coral' / etc.;
    none in denylist = KEEP. Recovers bare-TitleCase house WYSIWYG OOS
    listing."""
    p = _by_title(products, "Strawberry Shortcake Colony 2.5 -WYSIWYG")
    assert _should_keep(p, UC_CATEGORY_FILTER) is True


# ─── Test 22 (CTK-037 Q-8 (a)): empty-PT cross-vendor TSA keeps ───────────────
def test_filter_keeps_empty_pt_cross_vendor_tsa(products):
    """TSA Bill Murray Acropora-WYSIWYG has product_type='' — cross-vendor
    TSA prefix preserved at parse layer; filter passes via empty-PT
    allowlist + no denylisted tags."""
    p = _by_title(products, "TSA Bill Murray Acropora-WYSIWYG")
    assert _should_keep(p, UC_CATEGORY_FILTER) is True


# ─── Test 23 (CTK-037 Q-8 (a)): empty-PT cross-vendor WWC keeps ───────────────
def test_filter_keeps_empty_pt_cross_vendor_wwc(products):
    """WWC Grafted Firewalker Montipora-WYSIWYG has product_type='' —
    cross-vendor WWC prefix preserved at parse layer; filter passes via
    empty-PT allowlist + no denylisted tags."""
    p = _by_title(products, "WWC Grafted Firewalker Montipora-WYSIWYG")
    assert _should_keep(p, UC_CATEGORY_FILTER) is True


# ─── Test 24 (CTK-037 + tag_denylist): empty-PT PNS rejects via denylist ──────
def test_filter_rejects_empty_pt_pns_via_tag_denylist(products):
    """PNS Deep Cycle (16 oz) is the equipment-leak case in UC's empty-PT
    bucket — product_type='' PASSES the allowlist (Q-8 (a)) but tags 'goods'
    + 'PNS' BOTH appear in tag_denylist = REJECT. This is the orthogonal-
    axis discipline: empty-PT recovery + tag_denylist closes the gap on
    UC's ~25% equipment contamination rate in empty-PT (distinct from
    Battlecorals' <1% rate). Key new test class for CTK-085 Session 3 —
    no analog in Battlecorals' empty tag_denylist."""
    p = _by_title(products, "PNS Deep Cycle (16 oz)")
    assert _should_keep(p, UC_CATEGORY_FILTER) is False


# ─── Test 25 (CTK-037): Drygoods PT rejects via allowlist miss ────────────────
def test_filter_rejects_drygoods_pt_allowlist_miss(products):
    """Activated Carbon 1000ml has product_type='Drygoods' — NOT in
    allowlist (only CORAL / Coral / "" are) = REJECT. Tags 'goods' / '25-50'
    / 'triton' would ALSO trigger tag_denylist on 'goods' but allowlist
    rejection fires first at _should_keep evaluation. Two REJECT paths
    converge on this product (allowlist + denylist both reject)."""
    p = _by_title(products, "Activated Carbon 1000ml")
    assert _should_keep(p, UC_CATEGORY_FILTER) is False


# ─── Test 26 (CTK-037): permissive default when no category_filter block ──────
def test_filter_unique_corals_permissive_when_no_block(products):
    """Phase 2 vendor onboarding inheritance — None or {} = no gate. Every
    fixture product passes (including the rejected PNS Deep Cycle +
    Activated Carbon — without the filter block, they would land in
    vendor_listings)."""
    for p in products:
        assert _should_keep(p, None) is True
        assert _should_keep(p, {}) is True


# ─── Test 27 (CTK-037): kept/skipped count pins fixture composition ───────────
def test_filter_unique_corals_kept_count_matches(products):
    """Fixture composition: 6 KEEP + 2 REJECT under UC_CATEGORY_FILTER.
        KEEP (6):
          - UC Burnt Orange OG Jawbreaker-WYSIWYG (CORAL allowlist)
          - Unique Corals Rainbow Hyacinthus (empty-PT Q-8 (a))
          - Strawberry Shortcake Colony 2.5 -WYSIWYG (empty-PT Q-8 (a) + OOS)
          - TSA Bill Murray Acropora-WYSIWYG (empty-PT Q-8 (a) cross-vendor)
          - WWC Grafted Firewalker Montipora-WYSIWYG (empty-PT cross-vendor)
          - UC Mystic Montipora-WYSIWYG (CORAL allowlist + OOS)
        REJECT (2):
          - PNS Deep Cycle (16 oz) (empty-PT but tag_denylist 'goods'+'PNS')
          - Activated Carbon 1000ml (Drygoods PT allowlist-miss)
    Pins fixture composition + filter behavior; if a fixture entry is added/
    removed the count line documents the intent."""
    kept = sum(1 for p in products if _should_keep(p, UC_CATEGORY_FILTER))
    skipped = sum(1 for p in products if not _should_keep(p, UC_CATEGORY_FILTER))
    assert kept == 6, f"expected 6 kept, got {kept}"
    assert skipped == 2, (
        f"expected 2 skipped (PNS Deep Cycle via tag_denylist + Activated "
        f"Carbon via PT-allowlist-miss); got {skipped}"
    )


# ─── Test 28 (CTK-037 Session 5.5): predicate normalization keeps None/absent ─
def test_filter_normalizes_none_product_type_to_empty_string(products):
    """CTK-037 Session 5.5 — None or key-absent product_type normalizes to ""
    so UC empty-string allowlist entry matches both Shopify shape variants.
    Prevents silent recall regression if Shopify shifts empty-bucket
    representation. Mirror of test_jf_parse + test_tsa_parse + test_
    battlecorals_parse precedent."""
    product_none = {"product_type": None, "title": "Some coral", "tags": []}
    product_missing = {"title": "Some coral", "tags": []}  # key absent
    cf = UC_CATEGORY_FILTER  # has "" in allowlist
    assert _should_keep(product_none, cf) is True
    assert _should_keep(product_missing, cf) is True


# ─── Test 29 (CTK-037 Session 5.5): normalization is symmetric (rejects too) ──
def test_filter_rejects_none_product_type_when_empty_not_in_allowlist(products):
    """CTK-037 Session 5.5 — normalization is symmetric; None still rejects
    when "" is not in the allowlist. Mirror of the JF + TSA + Battlecorals
    precedent tests."""
    product = {"product_type": None, "title": "Some coral", "tags": []}
    cf = {"product_type_allowlist": ["CORAL"], "tag_denylist": []}
    assert _should_keep(product, cf) is False


def main() -> int:
    products = _load_fixture()
    print(f"loaded fixture: {len(products)} products from {FIXTURE_PATH}")

    tests = [
        test_html_hash_first_product_keys,
        test_house_lineage_normalize_no_prefix_synthesis,
        test_uc_abbreviation_prefix_lowercased_preserved,
        test_uc_full_word_prefix_lowercased_preserved,
        test_cross_vendor_prefix_lowercased_preserved,
        test_oos_product_in_stock_false,
        test_in_stock_product_in_stock_true,
        test_first_sku_pick_non_empty,
        test_product_url_absolute,
        test_vendor_image_url_first_image,
        test_currency_usd_default,
        test_lineage_flag_uc_abbreviation_fires_vendor_named,
        test_lineage_flag_uc_full_word_stays_unknown,
        test_lineage_flag_cross_vendor_prefix_fires_vendor_named,
        test_lineage_flag_bare_titlecase_stays_unknown,
        test_lineage_flag_pns_equipment_fires_but_filtered,
        test_category_inference,
        test_filter_keeps_coral_pt_uc_abbreviation,
        test_filter_keeps_coral_pt_oos_uc_mystic,
        test_filter_keeps_empty_pt_uc_full_word,
        test_filter_keeps_empty_pt_bare_titlecase,
        test_filter_keeps_empty_pt_cross_vendor_tsa,
        test_filter_keeps_empty_pt_cross_vendor_wwc,
        test_filter_rejects_empty_pt_pns_via_tag_denylist,
        test_filter_rejects_drygoods_pt_allowlist_miss,
        test_filter_unique_corals_permissive_when_no_block,
        test_filter_unique_corals_kept_count_matches,
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
