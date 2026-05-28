"""POTO (Pieces of the Ocean) — Phase 2 scraper #10 (CTK-088).

Vendor: https://piecesoftheocean.com (Shopify behind Cloudflare, hourly
cadence per arch §2.7 decision #15 + 0019_add_poto_vendor.sql, vendor_id=10).
New York, NY vendor per .claude/research/phase-1.5-vendor-scan.md §10.

COORDINATION ANCHOR (the load-bearing context for future-Jon at 11pm):
This scraper captures POTO's CURRENT BUYABLE live-sale coral inventory off
its own Shopify storefront. POTO's primary auction-side capture is ReefnBid
(CTK-007) — parked Tier 4 (ReefnBid shifted to React SPA + Cloudflare WAF +
Hanko auth; re-opens on a Hunter-tier customer ask OR R2R demand >=3). So
POTO listings from this scraper are the Shopify live-sale surface, NOT the
auctions. The §10 vendor-scan "interesting POTO inventory is on ReefnBid,
showroom is a fraction" verdict is STALE — the 2026-05-28 pre-flight found
POTO runs its coral drops THROUGH its own Shopify (3,450+ dated live-sale /
lightning-sale items). POTO Shopify IS the drop channel.

robots.txt (checked 2026-05-28 per arch §2.5): empty on the un-followed
homepage 301; re-probe with -L if needed. Not load-bearing given the
powered-by: Shopify header + clean /products.json. Honors arch §2.5
polite-scraper hygiene (request_delay_sec: 2, no login-walled content).

Five-signal Shopify confirmation pre-flight (vendor-scan false-positive
precedent invariant per CTK-085 Session 1c AquaSD-split-to-CTK-090): clean.
powered-by: Shopify + Shopify server-timing + Shopify.shop JS global +
/products.json HTTP 200 + canonical 13-key product shape. Cloudflare sits
in front (CDN) but did not block the JSON endpoint. Documented in poto.yaml
products_path block.

CATALOG SHAPE — the defining characteristic (permanent live-sale archive):
Full-catalog sweep 2026-05-28 = 5,466 products across 22 pages. POTO never
removes sold-out drops, so the catalog is a growing graveyard — of 5,466
only ~164 are buyable at any moment (159 kept after the filter; the buyable
count is a point-in-time figure that fluctuates with POTO's live-sale
schedule). This drives two CTK-088 design decisions:

  (A) in_stock_only=true (framework extension, scrapers/common/
      parse_shopify._should_keep 4th gate). Keeps ONLY buyable items out of
      the diff. Without it, vendor_listings would hold ~5,300 never-ageing
      sold-out rows polluting /new + /deals + analytics with no restock
      signal. Opt-in per-vendor; the other 9 vendors leave it unset
      (default false = fleet behavior, byte-identical — verified
      no-regression at CTK-088).

  (B) BUYABLE INVENTORY CLUSTERS AT THE PAGINATION TAIL. POTO's permanent
      signature stock (product_type 'collection' 132 buyable + 'poto-gems'
      16) is ordered LAST in /products.json (pages 21-22); the dated
      sold-out archive fills pages 1-20. So max_pages must paginate the
      WHOLE archive (30, with growth headroom), and a created_at early-stop
      optimization is CONTRAINDICATED (it would stop before the buyable
      tail). As the archive grows, buyable stock pushes to later pages —
      max_pages must stay ahead (post-ship watch in poto.yaml).

FILTER (ratified /lead-backend 2026-05-28 after impl re-sweep contradicted
the plan's "coral-pure, no allowlist" premise): product_type_allowlist of
the STABLE coral type-names ('live sale' / 'lightning sale' / 'collection' /
'poto-gems' / 'wysiwyg' / '') drops buyable non-coral the plan pre-flight
missed — 4 merch (ReefnBid tee / lens filter / POTO viewing glasses / POTO
hoodie) + 1 Gift Card, all image-bearing (frontend has_image gate won't
catch them). Empty-string '' is kept by NECESSITY — 5 buyable cross-vendor
corals (WWC/TSA/POTO) carry empty product_type. The dated drop buckets live
in TAGS (not allowlisted), so this isn't the rotating-bucket rot the plan
feared. One macroalgae leak ('Atomic Broccoli Macroalgae', PT 'live sale',
no tag) accepted per the Battlecorals 1-anemone precedent. Full rationale +
post-ship watch in poto.yaml category_filter block.

Title-shape: cross-vendor lineages (WWC / TSA / JF / RRU / QCC prefixes) +
POTO house pieces ('POTO X' — POTO Solar Pop, POTO Starscream, POTO Genghis
Khan). originator_prefix=null (no POTO-attributed seed-list canonicals to
synthesize against; cross-vendor prefixes match at matcher stages 1-2
directly). Same disposition as Vivid + Reef Chasers.

Known v1 behavior (not a defect): when a POTO item sells out, in_stock_only
stops re-parsing it -> it ages out of views via the §2.2 ~7-day stale-
last_seen_at filter, exactly like a vendor that removed an item. There's a
window where a just-sold-out POTO coral still shows in-stock. Fleet-standard;
faster OOS accuracy is the shared cohort-comparison fix in open-items
Q-Backend-1 (deferred for v1).

Pure /products.json shakedown — no per-vendor overrides. All scrape behavior
inherited from scrapers.common.parse_shopify via the shared run.py
orchestrator (in_stock_only is the second per-vendor parse extension after
CTK-086 Q-4 tag_allowlist). The vendors row + scrapers/vendors/poto.yaml
carry all config.

Test fixture regen path (CTK-024/025/026/027/Battlecorals/UC/Vivid/RC convention):
  curl -sS "https://piecesoftheocean.com/products.json?limit=250&page=N" \\
    -H "User-Agent: <Chrome UA per scrapers/common/http.py>" \\
    > /tmp/poto_pageN.json
  # Pick ~3 representative products per fixture discipline (NOT one-per-bucket):
  # a buyable coral (in_stock_only keep), a sold-out coral (in_stock_only
  # drop), a buyable merch item (PT-allowlist drop), the macroalgae
  # (accepted-leak / in coral PT). Write to scrapers/tests/fixtures/poto/
  # products.sample.json. See test_poto_parse.py for the expected assertions.
"""
