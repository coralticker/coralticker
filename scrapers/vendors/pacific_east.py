"""Pacific East Aquaculture — Phase 1 scraper #1 (CTK-024).

Vendor: https://pacificeastaquaculture.com (Shopify, daily new-arrival flow,
500-2000 listings — smallest catalog of the four Phase 1 vendors). Mardela
Springs, MD; 14 years in business; Jon's local vendor.

robots.txt (checked 2026-05-03 per arch §2.5): no /products.json disallow.
Honors arch §2.5 polite-scraper hygiene posture.

Pure /products.json shakedown — no per-vendor overrides. All scrape behavior
inherited from scrapers.common.parse_shopify via the shared run.py orchestrator.
The vendors row + scrapers/vendors/pacific_east.yaml carry all config; this
module is the hook point where vendor-specific overrides would land if PE's
site shape ever requires them (none anticipated for the canonical Shopify
shakedown).
"""

# This file is intentionally code-light. The orchestrator dispatches by
# vendors.platform ('shopify') — no per-vendor function needs to be called.
# When future vendors require pre-parse / post-parse hooks (Tidal Gardens
# custom HTML, ReefnBid auctions), define them here as module-level callables
# that scrapers.common.run.run() looks up by slug.
