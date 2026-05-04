"""World Wide Corals — Phase 1 scraper #2 (CTK-025).

Vendor: https://worldwidecorals.com (Shopify, hourly cadence per arch §2.7
+ seed.sql:39 — continuous new-arrival flow + Sunday-heavy live sales).
Orlando, FL; one of the largest US online coral retailers; high-frequency
catalog churn is the load-bearing reason for the hourly tier.

robots.txt (checked 2026-05-04 per arch §2.5): no /products.json disallow.
The disallow list covers checkout-related paths (/cart, /account, /checkout,
collection sort/filter URLs) — same shape as PE's. Honors arch §2.5
polite-scraper hygiene posture.

WWC originates named pieces (Dragon Soul Torch, Mango Tango Echinata, etc.).
Title shape verified at session-1 spot-check (2026-05-04): mixed — ~30% of
first-20 titles carry "WWC " prefix (e.g., "WWC Mango Tango Echinata"),
~70% drop it (e.g., "Hypnotic Aussie Lord", "Dragon Soul Torch"). YAML
sets originator_prefix='wwc' so matcher §3.4 stage 3 (canonical-implicit-
prefix) catches the no-prefix 70%; the prefix-bearing 30% match at stage 1
or 2 directly. See wwc.yaml D3 comment for evidence.

Pure /products.json shakedown — no per-vendor overrides. All scrape
behavior inherited from scrapers.common.parse_shopify via the shared run.py
orchestrator. The vendors row + scrapers/vendors/wwc.yaml carry all config;
this module is the hook point where vendor-specific overrides would land
if WWC's site shape ever requires them (none anticipated for the canonical
Shopify shakedown).
"""

# This file is intentionally code-light. The orchestrator dispatches by
# vendors.platform ('shopify') — no per-vendor function needs to be called.
# When future vendors require pre-parse / post-parse hooks (Tidal Gardens
# custom HTML, ReefnBid auctions), define them here as module-level callables
# that scrapers.common.run.run() looks up by slug.
