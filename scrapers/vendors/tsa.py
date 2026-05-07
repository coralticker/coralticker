"""Top Shelf Aquatics — Phase 1 scraper #3 (CTK-026).

Vendor: https://topshelfaquatics.com (Shopify, event-aware cadence per arch
§2.7 + decision #15 + seed.sql:40 — 15-min during Sat/Sun 11a-11p ET drop
window, hourly-always otherwise per CTK-026 D3). Florida; ~3000-listing
catalog (largest in Phase 1); known for batch drops in 10-15-minute waves
during the Sat/Sun window — load-bearing reason for the event-aware tier.

robots.txt (checked 2026-05-07 per arch §2.5): no /products.json disallow.
Honors arch §2.5 polite-scraper hygiene posture.

TSA originates named coral pieces ("TSA Deep Soul Favia", "TSA Archangel
Goniopora", etc.). Q-A title-shape spot-check 2026-05-07: 89/250 (~36%) of
page-1 titles carry "TSA " prefix; pattern matches WWC's ~30% prefix-bearing
rate that locked CTK-025 to originator_prefix='wwc'. The first-20-at-limit=20
sample returned 1/20 (recency-skewed: TSA's catalog at small limit returns
recent fish/invert arrivals; coral named pieces appear deeper). Locked
originator_prefix='tsa' per /lead-backend weigh 2026-05-07 — matcher §3.4
stage 3 (canonical-implicit-prefix) catches no-prefix corals like "Beast Boy
Favia Coral" that share the TSA-style internal SKU shape (CTOX...) but drop
the prefix in the title. See tsa.yaml D3-equivalent comment for evidence.

Pure /products.json shakedown — no per-vendor overrides. All scrape
behavior inherited from scrapers.common.parse_shopify via the shared run.py
orchestrator. The vendors row + scrapers/vendors/tsa.yaml carry all config;
this module is the hook point where vendor-specific overrides would land
if TSA's site shape ever requires them (none anticipated for the canonical
Shopify shakedown).

Test fixture regen path (CTK-024/025 convention; CTK-026 R2 fold):
  curl -sS "https://topshelfaquatics.com/products.json?limit=250" \
    -H "User-Agent: <Chrome UA per scrapers/common/http.py>" \
    > /tmp/tsa_page1.json
  # Pick 7 representative products by title (TSA-prefix coral OOS / TSA-prefix
  # coral in-stock / no-prefix coral OOS / no-prefix coral in-stock / fish /
  # multi-variant merch / no-SKU edge case) and write to
  # scrapers/tests/fixtures/tsa/products.sample.json. See test_tsa_parse.py
  # for the expected shape assertions the fixture must continue to satisfy.
"""

# This file is intentionally code-light. The orchestrator dispatches by
# vendors.platform ('shopify') — no per-vendor function needs to be called.
# When future vendors require pre-parse / post-parse hooks (Tidal Gardens
# custom HTML, ReefnBid auctions), define them here as module-level callables
# that scrapers.common.run.run() looks up by slug.
