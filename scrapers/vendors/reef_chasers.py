"""Reef Chasers — Phase 2 scraper #9 (CTK-086 Session 3).

Vendor: https://reefchasers.com (Shopify, hourly cadence per arch §2.7
decision #15 + 0018_add_reef_chasers_vendor.sql, vendor_id=9). TN vendor,
10k-gal facility, fish + invert + coral multi-category catalog per
.claude/research/phase-1.5-vendor-scan.md close summary; QCC swap candidate
selected 2026-04-24. 249-product steady-state catalog at 2026-05-28 —
small-catalog floor comparable to JF (452) at the lower end.

robots.txt (checked 2026-05-28 per arch §2.5): explicit "# Shopify
storefront. Public product, collection, page, blog, policy, cart, and
localized HTML is crawlable." preamble. Standard Shopify Allow / Disallow
shape. UCP/MCP endpoint at /api/ucp/mcp + agents.md guidance — honors
agent-aware Shopify storefront posture. Honors arch §2.5 polite-scraper
hygiene posture.

Five-signal Shopify confirmation pre-flight (vendor-scan false-positive
precedent invariant per CTK-085 Session 1c AquaSD-split-to-CTK-090): all
clean. Documented in reef-chasers.yaml products_path block. Canonical
public domain is reefchasers.com (reef-chasers.com is NXDOMAIN; hyphenated
form is the .myshopify.com shop slug only).

Reef Chasers data-shape sub-divergence (the reason CTK-086 Q-4 landed):

  (A) product_type is EMPTY ('') across ALL 249 products — taxonomy lives
      entirely in tags. Distinct from every prior Shopify vendor (PE/WWC/
      TSA/JF product_type buckets; Battlecorals taxonomic-genus ~70 entries;
      UC structural-class CORAL/Drygoods; Vivid 'WYSIWYG Coral'/'Corals and
      Inverts' buckets). RC is the first vendor whose coral signal is a tag,
      not a product_type. The Q-4 tag_allowlist framework extension (landed
      CTK-086 Session 2 in scrapers/common/parse_shopify._should_keep)
      absorbs this — tag_allowlist: ['Coral'] is the load-bearing gate.

  (B) 'Coral' umbrella tag is the SOLE + COMPLETE coral signal. Full-catalog
      walk 2026-05-28: 143 'Coral'-tagged rows, and every coral-subtype-tagged
      row (SPS 63 / Acropora 49 / LPS 36 / Zoanthid 26 / Soft Coral 25 /
      Mushroom 11 / Chalice 8 / etc.) ALSO carries the 'Coral' umbrella —
      coverage gap = 0. The 106 non-'Coral' rows are fish / equipment / food
      / supplements, correctly excluded by tag_allowlist miss.

Reef Chasers title-shape findings (full 249-product walk 2026-05-28):

  (A) RC self-prefix bearing: "RC X" prefix on 79/143 coral titles (~55%;
      e.g., "RC Space Invader Chalice Frag", "RC Cosmic Calamity Favia",
      "RC Ectoplasm Acropora", "RC Jungle Juice Acropora", "RC California
      Kush Acropora"). RC clearly originates named house lineages.

  (B) originator_prefix=null per CTK-024 PE + Vivid precedent. Seed-list
      (.claude/research/named-coral-seed-list.md) has ZERO Reef-Chasers-
      attributed canonical entries — RC is not among the priority originator
      vendors. With no "RC X" canonical to synthesize against, matcher §3.4
      stage 3 synthesis is a no-op for RC pieces; null is correct TODAY.
      Forward note: RC's house lineages are legitimate named-coral originator
      candidates; if seed-list expansion adds RC canonicals, flip
      originator_prefix to 'rc'. Flagged for /lead-architect / seed-list-
      expansion awareness (not a CTK-086 scraper-side blocker).

  (C) Cross-vendor propagation: TSA / JF / PR / TGC prefixes observed on RC
      catalog (e.g., "TSA Sour Patch Acropora", "JF Raja Rampage Frag", "PR
      Fruity Pebbles Acropora", "TGC Red Wing Millepora"). Matcher §3.4
      stages 1-2 catch these directly via canonical-exact / canonical-prefix
      IF the seed-list has the right cross-vendor canonical entries; no
      special parse-layer config.

  (D) infer_lineage_flag fires on 2-4 char ALL-CAPS-prefix titles — RC
      self-prefix + cross-vendor TSA/JF/PR/TGC prefixes all fire
      'vendor-named'. Bare-TitleCase pieces land 'unknown'.

Category filter: tag_allowlist: ['Coral'] (Q-4 framework) + tag_denylist
(11 tags, belt-and-suspenders, DORMANT at ship — zero co-occurrence with
'Coral' at 2026-05-28 walk; all spellings verified verbatim-present). Full
discussion in reef-chasers.yaml category_filter block.

Pure /products.json shakedown — no per-vendor overrides. All scrape behavior
inherited from scrapers.common.parse_shopify via the shared run.py
orchestrator (framework verbatim from CTK-086 Session 2 Vivid ship +
Q-4 tag_allowlist extension, already in main). The vendors row +
scrapers/vendors/reef-chasers.yaml carry all config; this module is the
hook point where vendor-specific overrides would land if RC's site shape
ever requires them (none anticipated for the canonical Shopify shakedown).

Test fixture regen path (CTK-024/025/026/027/Battlecorals/UC/Vivid convention):
  curl -sS "https://reefchasers.com/products.json?limit=250" \\
    -H "User-Agent: <Chrome UA per scrapers/common/http.py>" \\
    > /tmp/reef_chasers_page1.json
  # Pick 2-3 representative products by title per F3 fold (NOT one-per-tag):
  # one 'Coral'-tagged coral with RC self-prefix (e.g., RC Space Invader
  # Chalice Frag — exercises tag_allowlist hit + RC lineage_flag), one
  # Fish-tagged row (e.g., Blue Hippo Tang — exercises tag_allowlist miss +
  # tag_denylist Fish/Tang double), one coral-keyword-but-non-coral edge
  # (e.g., Two Little Fishes AcroPower — coral-food, no 'Coral' tag, no
  # denylist tag; allowlist-miss silent drop is correct). Write to
  # scrapers/tests/fixtures/reef_chasers/products.sample.json. See
  # test_reef_chasers_parse.py for the expected shape assertions the fixture
  # must continue to satisfy.
"""
