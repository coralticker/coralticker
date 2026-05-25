"""Unique Corals — Phase 2 scraper #6 (CTK-085 Session 3).

Vendor: https://uniquecorals.com (Shopify, hourly cadence per arch §2.7
decision #15 + 0011_add_unique_corals_vendor.sql, vendor_id=6). Los Angeles
CA West Coast must-have per .claude/research/phase-1.5-vendor-scan.md §5
("West Coast must-have, established WYSIWYG presence"); 524-product steady-
state catalog at 2026-05-25.

robots.txt (checked 2026-05-25 per arch §2.5): explicit "Shopify storefront.
Public product, collection, page, blog, policy, cart, and localized HTML
is crawlable." preamble; UCP/MCP endpoint advertised at /api/ucp/mcp +
agents.md guidance — honors agent-aware Shopify storefront posture.
Standard Shopify Allow / Disallow shape. Honors arch §2.5 polite-scraper
hygiene posture.

Five-signal Shopify confirmation pre-flight (vendor-scan false-positive
precedent invariant per CTK-085 Session 1c AquaSD-split-to-CTK-090): all
clean. Documented in unique_corals.yaml products_path block.

Unique Corals title-shape findings (full 524-product walk 2026-05-25):

  (A) Dual self-prefix bearing: 'Unique Corals X' full-word (80 / 524 =
      15.3%) + 'UC X' abbreviation (49 / 524 = 9.3%) = combined 24.6%
      self-prefix rate. Distinct from all prior Phase 1+2 vendors:
      Battlecorals 0%, JF 60%, WWC ~30%, TSA ~36%, PE null. UC is the
      FIRST vendor with structured dual-prefix shape — abbreviation +
      full-word coexist in catalog usage. Examples:
        - 'Unique Corals Rainbow Hyacinthus' (full-word)
        - 'Unique Corals Electric Amethyst Millepora' (full-word)
        - 'UC Burnt Orange OG Jawbreaker-WYSIWYG' (abbreviation)
        - 'UC Mystic Montipora-WYSIWYG' (abbreviation)
        - 'UC Signature "Glitter Bomb" Goniopora' (abbreviation, quoted-name)

  (B) Bare-title catalog (63.7%, 334 / 524): house WYSIWYG pieces without
      any vendor prefix — 'Strawberry Shortcake Colony 2.5 -WYSIWYG',
      'Wildberry Chalice-WYSIWYG', 'Tangerine Cyphastrea-WYSIWYG', 'True
      UC Hologram Branching Hammer- WYSIWYG'. Same shape as Battlecorals
      house lineages; matcher §3.4 stage 3 synthesis is the lineage-capture
      mechanism via originator_prefix='uc' YAML lock.

  (C) Cross-vendor propagation: 11.6% of titles (~61 / 524) carry 2-4 char
      ALL-CAPS prefix shape catching cross-vendor lineages. Top
      distribution: ARID (10), WWC (8), JF (6), TSA (6), ECM (5), PC (2),
      PNS (2). Examples:
        - 'WWC Grafted Firewalker Montipora-WYSIWYG'
        - 'TSA Bill Murray Acropora-WYSIWYG'
        - 'JF Cherry Cobbler Acropora'
      Matcher §3.4 stage 1/2 catches these directly via canonical-exact /
      canonical-prefix IF the seed-list has the right cross-vendor canonical
      entries.

  (D) infer_lineage_flag fires on 2-4 char ALL-CAPS-prefix titles —
      'UC X' (UC abbreviation + 'WWC X' / 'TSA X' / cross-vendor variants
      all fire 'vendor-named'. 'Unique Corals X' full-word does NOT fire
      ('Unique' is 6-char TitleCase, not ALL-CAPS-prefix shape) — those
      lands lineage_flag='unknown' at parse time. Bare-TitleCase house
      lineages ('Strawberry Shortcake Colony') also land 'unknown'.
      Matcher §3.4 stage 3 originator_prefix='uc' synthesis is the real
      lineage-capture mechanism for the full-word + bare-title slices.
      Note: PNS-tagged equipment (e.g., 'PNS Deep Cycle (16 oz)') also
      fires 'vendor-named' lineage_flag at parse layer; rejected at
      downstream filter via tag_denylist + empty-PT discipline.

Originator_prefix='uc' convention divergence from Battlecorals (CTK-085
Session 2 Q-1 sibling): Battlecorals YAML used originator_prefix='battlecorals'
(slug form, full-word) because seed-list there uses 'Battlecorals X'
canonical_name shape. UC YAML uses originator_prefix='uc' (abbreviation form)
because seed-list there uses 'UC X' canonical_name shape (21 UC-attributed
entries: UC Strawberry Shortcake OG, UC Burnt Orange OG Jawbreaker, UC
Stranger Tort, UC Cookie Monster Acropora, UC Pikachu, UC Aquaman, UC
Fallen Phoenix, UC Tyree Pinky the Bear, etc.). The principle:
originator_prefix matches seed-list canonical_name normalization output,
NOT the slug. Documented in unique_corals.yaml D1 block.

Dual-shape matcher limitation: 'Unique Corals X' catalog titles (80
listings, 15.3%) do NOT synthesize cleanly against seed-list 'UC X'
canonicals via matcher stage 3 alone — stage 3 synthesizes 'uc ' +
normalized_title, so 'Unique Corals Rainbow Hyacinthus' normalizes to
'unique corals rainbow hyacinthus' and the synthesis path would need stage 2
vendor-prefix stripping to bridge 'Unique Corals' → bare. Out-of-scope for
CTK-085 scraper-side config. Flagged for /lead-architect awareness as
CTK-085 Session 3 Q-1: UC raises the multi-prefix matcher question
explicitly (sibling to Battlecorals Session 2 Q-1 stage-3-primary-path
documentation ask).

First-variant SKU non-null rate spot-check 2026-05-25: 448/524 = 85.5% —
between JF's 100% and TSA's tested rate. parse_shopify's first-non-empty-
SKU pick at _normalize_product gracefully falls back to null vendor_sku
when all variants lack SKUs. No inter-product SKU collisions surveyed at
this walk (full survey deferred to /lead-backend close-monitor if needed;
spot-check matches PE/WWC pattern).

Catalog-shape note: UC's product_type carries structural-class granularity
('CORAL' / 'Drygoods' / 'Panta Rhei' / 'live rock' / 'CLEANUP' / etc.),
distinct from Battlecorals' taxonomic-genus shape (~70 entries: Acropora
Tenuis, Acropora Microclados, etc.) and JF's bucket shape (SPS / LPS /
WYSIWYG / Frag). 13 distinct product_types observed; empty-PT bucket carries
~25% equipment contamination (vs. Battlecorals' <1%) — tag_denylist
belt-and-suspenders is mandatory per feedback_rotating_bucket_allowlist.md
sibling discipline (rotating-OUT inverse: empty-PT bucket is mixed-content
not rotating-bucket, but tag-noise sweep technique applies). Full
discussion in unique_corals.yaml category_filter block.

FLASHSALE bucket disposition: rotating-promotional bucket shape per
feedback_rotating_bucket_allowlist.md discipline; 2 items at 2026-05-25
walk (1 coral + 1 'Bed sheet' obvious miss). Excluded from allowlist pending
multi-day sampling. Flagged as Q-2 for /lead-backend close-monitor re-
evaluation after 2-3 weeks of observations confirm bucket composition.

Pure /products.json shakedown — no per-vendor overrides. All scrape
behavior inherited from scrapers.common.parse_shopify via the shared
run.py orchestrator. The vendors row + scrapers/vendors/unique_corals.yaml
carry all config; this module is the hook point where vendor-specific
overrides would land if UC's site shape ever requires them (none anticipated
for the canonical Shopify shakedown).

Phase 2.5 event-aware overlay CTK trigger: hourly-only v1 ship per Q-2
disposition (CTK-085 plan §Decisions). 2-3 Monday Flash Sales empirical
drop-density observations post-ship trigger the Phase 2.5 overlay CTK
scaffold (open-items.md L44 graduates to Resolved at CTK-085 Session 3
wrap; Phase 2.5 trigger row appended to open-items.md Open section).
Likely empirical-window start = first Monday post-2026-05-25 = 2026-06-01.

Test fixture regen path (CTK-024/025/026/027/Battlecorals convention):
  curl -sS "https://uniquecorals.com/products.json?limit=250" \\
    -H "User-Agent: <Chrome UA per scrapers/common/http.py>" \\
    > /tmp/unique_corals_page1.json
  # Pick 8 representative products by title: UC abbreviation in CORAL
  # bucket (UC Burnt Orange OG Jawbreaker-WYSIWYG), UC full-word in
  # empty-PT (Unique Corals Rainbow Hyacinthus), bare-WYSIWYG empty-PT
  # (Strawberry Shortcake Colony 2.5 -WYSIWYG OOS case), cross-vendor TSA
  # empty-PT (TSA Bill Murray Acropora-WYSIWYG), cross-vendor WWC empty-PT
  # (WWC Grafted Firewalker Montipora-WYSIWYG), UC abbreviation OOS in
  # CORAL (UC Mystic Montipora-WYSIWYG), equipment leak in empty-PT
  # via tag_denylist (PNS Deep Cycle (16 oz)), Drygoods PT allowlist-miss
  # (Activated Carbon 1000ml). Write to scrapers/tests/fixtures/
  # unique_corals/products.sample.json. See test_unique_corals_parse.py
  # for the expected shape assertions the fixture must continue to satisfy.
"""
