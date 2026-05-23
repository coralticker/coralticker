"""Jason Fox Signature Corals — Phase 1 scraper #4 (CTK-027).

Vendor: https://jasonfoxsignaturecorals.com (Shopify, drop-day-aware cadence
per arch §2.7 decision #15 + seed.sql:41 — hourly baseline + operator-fired
workflow_dispatch on announced drop days per CTK-027 D3 lean (α); 5-min
cadence + announcement-detection mechanism deferred to Phase 2 sub-minute-tier
work alongside Q2-1 worker per arch §2.7 + CTK-006). Originator vendor; <500-
listing steady-state catalog with anniversary/holiday drop spikes — smallest
catalog Phase 1 will see; closes Phase 1 vendor-scraper queue.

robots.txt (checked 2026-05-11 per arch §2.5): no /products.json disallow —
standard Shopify boilerplate (admin/cart/orders denied, /products.json
permitted). Honors arch §2.5 polite-scraper hygiene posture.

JF is the canonical signature-coral originator vendor. D4 title-shape spot-
check 2026-05-11: 12/20 page-1 titles carry "JF " prefix; rest carry collab
prefixes (CC, ORA, HUGOS, TYREE, TCR), one longform "JASON FOX", and 2
no-prefix pieces (SPECIAL PORITES, PEPPA PIG MONTI). Partial match per
plan D4 outcome (b) — confirms originator_prefix='jf' in jf.yaml; matcher
§3.4 stage 3 implicit-prefix synthesis covers the bare-name + collab-prefix
cases. Seed-list evidence remains overwhelming (12/12 JF entries bear "JF "
prefix), now anchored to a 60% bearing rate on the live catalog.

ALL-CAPS title shape (JF-wide): titles are ALL-CAPS-throughout ("JF SUNTAN
DIGI", not "JF Suntan Digi"). normalize_title lowercases all input so the
matcher §3.3 normalization absorbs the shape cleanly. infer_lineage_flag's
regex requires ALL-CAPS-prefix then title-case ("^[A-Z]{2,4}\\s+[A-Z][a-z]+")
— it WILL NOT fire on JF titles. JF rows land lineage_flag='unknown' at parse
time; matcher §3.4 stage 3 originator_prefix synthesis is the real lineage-
capture mechanism for this vendor. Documented for /lead-architect awareness;
no parse-layer code change in CTK-027 scope.

D2 SKU-collision spot-check 2026-05-11: at the parse-layer first-SKU pick
(parse_shopify.py:_normalize_product, which picks first non-empty variant
SKU and writes one vendor_listings row per product), JF has ZERO inter-
product collisions across the 452-row catalog — distinct from PE+WWC+TSA's
inter-product duplication pattern. The raw-variants scan surfaces 18
colliding variants but ALL are internal to the single "T Shirt" merch
product (6 colors × 3 sizes sharing per-size SKUs; product_type='tshirt'
denied by category_filter allowlist default — never enters Phase A persist).
JF validates D2 outcome (b): small-catalog originator-vendors diverge from
high-volume catalog vendors on SKU shape. The 0002_drop_vendor_sku_unique
amendment still load-bearing for PE+WWC+TSA; JF would have passed unique-
vendor_sku at the row level. Flagged to /lead-backend for /lead-architect
routing on arch §1.4 framing tune (catalog-size correlation with SKU-
collision pattern).

Pure /products.json shakedown — no per-vendor overrides. All scrape
behavior inherited from scrapers.common.parse_shopify via the shared run.py
orchestrator. The vendors row + scrapers/vendors/jf.yaml carry all config;
this module is the hook point where vendor-specific overrides would land
if JF's site shape ever requires them (none anticipated for the canonical
Shopify shakedown).

Test fixture regen path (CTK-024/025/026 convention):
  curl -sS "https://jasonfoxsignaturecorals.com/products.json?limit=250" \\
    -H "User-Agent: <Chrome UA per scrapers/common/http.py>" \\
    > /tmp/jf_page1.json
  # Pick 7 representative products by title (JF-prefix coral OOS / JF-prefix
  # coral in-stock / no-prefix coral / collab-prefix coral / longform JASON FOX
  # / multi-variant merch / empty-product_type real coral) and write to
  # scrapers/tests/fixtures/jf/products.sample.json. See test_jf_parse.py for
  # the expected shape assertions the fixture must continue to satisfy.
"""
