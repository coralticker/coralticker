"""Battlecorals — Phase 2 scraper #5 (CTK-085 Session 2).

Vendor: https://battlecorals.com (Shopify, daily cadence per arch §2.7
decision #15 + 0010_add_battlecorals_vendor.sql, vendor_id=5). SPS-strong
Austin TX vendor per .claude/research/phase-1.5-vendor-scan.md §4 ("SPS-
strong, ~7k IG following"); 499-product steady-state catalog at 2026-05-25.

robots.txt (checked 2026-05-25 per arch §2.5): explicit "Shopify storefront.
Public product, collection, page, blog, policy, cart, and localized HTML
is crawlable." preamble. Standard Shopify Allow / Disallow shape. Notable:
robots.txt advertises UCP/MCP endpoint at /api/ucp/mcp + agents.md guidance
— honors agent-aware Shopify storefront posture. Honors arch §2.5 polite-
scraper hygiene posture.

Five-signal Shopify confirmation pre-flight (vendor-scan false-positive
precedent invariant per CTK-085 Session 1c AquaSD-split-to-CTK-090): all
clean. Documented in battlecorals.yaml products_path block.

Battlecorals title-shape findings (full 499-product walk 2026-05-25):

  (A) Battlecorals self-prefix bearing rate: 0% — ZERO "BC " or "Battlecorals"
      prefix observed on house titles. Single outlier: "BC All stars grow
      out 2025!!!" (one grow-out announcement, not a coral listing). House
      titles bare-name throughout ("Hyperberry", "Joker 2.0", "PC Rainbow",
      "Genie of Death", "Blue Cyclobs", "Nexus Burst"). Distinct from JF's
      60% prefix-bearing + WWC's 30% + TSA's 36%. originator_prefix
      'battlecorals' YAML lock is justified by matcher §3.4 stage 3
      synthesis target (canonical_index lookup for "battlecorals X"
      seed-list entries), not by self-prefix-bearing rate.

  (B) Cross-vendor propagation: 4.8% of titles (24/499) carry 2-4 char
      ALL-CAPS prefix shape catching cross-vendor lineages: AV (Aquaforest?),
      RR, LRO, CC, TSA, WWC, ORA, ASD. Examples: 'TSA Bill Murray', 'WWC
      Purple Candle', 'ORA Pearlberry', 'AV Orange Crush', 'RR Blue Flame'.
      Battlecorals propagates other-vendor signature lineages — matcher
      §3.4 stage 1/2 catches these directly via canonical-exact /
      canonical-prefix IF the seed-list has the right cross-vendor canonical
      entries. No special parse-layer config; cross-vendor coverage is a
      seed-list-side concern.

  (C) Title-case mixed shape (distinct from JF ALL-CAPS-throughout): house
      titles are TitleCase ("Genie of Death") + lowercase noise ("acropora
      hyacinth" product_type) + ALL-CAPS-prefix cross-vendor + period-less
      taxonomic variants ('Acropora sp' alongside 'Acropora sp.').
      normalize_title lowercases all input; downstream cascade absorbs.

  (D) infer_lineage_flag fires on 4.8% of titles — the 2-4 char ALL-CAPS-
      prefix shape catches cross-vendor propagation but NOT Battlecorals'
      own house lineages (which are bare-TitleCase). Battlecorals house
      lineages land lineage_flag='unknown' at parse time; matcher §3.4
      stage 3 originator_prefix='battlecorals' synthesis is the real
      lineage-capture mechanism for house pieces. Documented for /lead-
      architect awareness; no parse-layer code change in CTK-085 scope.

First-variant SKU non-null rate spot-check 2026-05-25: 406/499 = 81% —
lower than JF's 100% but well above TSA's tested rate. parse_shopify's
first-non-empty-SKU pick at _normalize_product gracefully falls back to
null vendor_sku when all variants lack SKUs. No inter-product SKU
collisions surveyed at this walk (full survey deferred to /lead-backend
close-monitor if needed; spot-check matches PE/WWC pattern).

Catalog-shape note: Battlecorals' product_type field carries taxonomic-
granularity (genus + species, e.g., 'Acropora Tenuis') rather than bucket
shape (SPS/LPS/WYSIWYG). ~70 distinct product_types observed across 499
products; all coral (zero non-coral product_types). The category_filter
allowlist enumerates observed strings verbatim per CTK-037 precedent.
Rotating-OUT risk: new species_type strings hitting the catalog tomorrow
silently drop until allowlist amendment. Mitigation: scraper_runs.
listings_seen count drift watch at vendor close-monitor; full discussion
in battlecorals.yaml category_filter block.

Pure /products.json shakedown — no per-vendor overrides. All scrape
behavior inherited from scrapers.common.parse_shopify via the shared
run.py orchestrator. The vendors row + scrapers/vendors/battlecorals.yaml
carry all config; this module is the hook point where vendor-specific
overrides would land if Battlecorals' site shape ever requires them
(none anticipated for the canonical Shopify shakedown).

Test fixture regen path (CTK-024/025/026/027 convention):
  curl -sS "https://battlecorals.com/products.json?limit=250" \\
    -H "User-Agent: <Chrome UA per scrapers/common/http.py>" \\
    > /tmp/battlecorals_page1.json
  # Pick 8 representative products by title: BC self-prefix (single outlier),
  # cross-vendor ALL-CAPS prefix (TSA / WWC / ORA), Battlecorals house bare-
  # TitleCase named lineage (Hyperberry / Joker 2.0 / Genie of Death),
  # taxonomic product_type variant (Acropora Tenuis / Acropora sp. / Acropora
  # sp without period), empty product_type Battlebox grab-bag, in-stock vs.
  # OOS, multi-image, null first-variant SKU. Write to scrapers/tests/
  # fixtures/battlecorals/products.sample.json. See test_battlecorals_parse.py
  # for the expected shape assertions the fixture must continue to satisfy.
"""
