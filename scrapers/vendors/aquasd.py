"""AquaSD — Phase 2 scraper #7 (CTK-090 Session 1, 2026-05-26).

Vendor: https://aquasd.com (BigCommerce Stencil; daily cadence per arch
§2.7 + 0015_add_aquasd_vendor.sql, vendor_id=7). Top-6 must-have v1 launch
vendor per .claude/research/phase-1.5-vendor-scan.md §6 (amended 2026-05-25
post-CTK-085 Session 1c platform-detection probe; original §6 inference of
Shopify was invalidated by five-signal BigCommerce confirmation).

Five-signal BigCommerce Stencil confirmation (CTK-085 Session 1c 2026-05-25
+ CTK-090 Session 1 2026-05-26): meta platform tag, store_id-shaped CDN URL,
/products.json HTTP 404, /graphql token-gated, .php robots.txt. Server-
rendered category HTML with `?page=N` pagination — Playwright punt-trigger
(decision #50) does not fire; AquaSD stays Phase 2 per decision register
row #66.

robots.txt audit 2026-05-26 (per arch §2.5): User-agent: * disallows
admin / auth / cart / checkout / search / wishlist + faceted-filter
params (`_bc_fsnf=1`); zero explicit product-path disallow on the 21
coral genus paths in aquasd.yaml. Standard Chrome UA (decision #13)
falls outside the AI-scraper-bot block (Crawl-delay 10) — clean hygiene
posture.

AquaSD taxonomy walk 2026-05-26 (homepage nav grep): 41 single-segment
nav paths; 21 coral genus paths selected for category_paths. Non-coral
livestock (/fish, /inverts), site-org (/info, /contact-us, /more), algae
(/macro-algae), aggregator buckets (/frag-packs, /multiples-available,
/new-arrivals, /clearance), and parent rollups (/sps, /lps, /corals)
excluded. Three sub-class probes returned material findings:
  - /new-arrivals/ is a windowed view (192 cards across 3 pages, ZERO
    overlap with /acropora/) — breaks catalog-diff contract for full-
    catalog coverage. Rejected.
  - /sps/, /lps/, /softies/, /zoanthids/ parent paths partition cleanly
    EXCEPT /softies/ ∩ /zoanthids/ = 57 cards overlap. diff.classify
    product_url dedup absorbs at persist time.
  - /auctions/ surface is a third-party eBay-API JS widget (zero
    data-product-id cards; JS fallback "No active eBay auctions found
    right now."). Cannot be scraped by static HTML parser. Out of v1
    scope; future-CTK Playwright/eBay-API integration.

Silent-OOS gap: Stencil hides OOS items from category-page view (probe
2026-05-26 confirmed: zero out-of-stock markers across acropora / sps /
lps page-1 64-card sweeps). All parsed cards land in_stock=True; OOS-
via-disappearance gap is not currently surfaced by diff.classify (items
absent from scrape aren't iterated; existing DB rows stay at last-seen
in_stock value). Documented in aquasd.yaml; flagged for /lead-backend
Q-N — sibling-CTK or open-items.md entry for cohort-based OOS detection
at persist time.

Card markup anchor (Stencil canonical):
  <li class="product">
    <article class="card" data-name="..." data-product-category="..."
             data-product-price="..." data-entity-id="..." data-position="..."
             data-test="card-NNNNN" data-event-type="list">
      <figure class="card-figure">
        <a class="card-figure__link" href="https://aquasd.com/<slug>/" ...>
          <img class="lazyload card-image" src="https://cdn11.bigcommerce.com/...">
        </a>
        <figcaption class="card-figcaption">
          <button class="quickview" data-product-id="NNNNN">Quick view</button>
          ...
        </figcaption>
      </figure>
      <div class="card-body">
        <h3 class="card-title"><a aria-label="TITLE, $PRICE" href="...">TITLE</a></h3>
        <div class="card-text" data-test-info-type="price">...</div>
      </div>
    </article>
  </li>

Per-card extraction reads data-* attrs on <article> (clean structured
fields, no display-text parsing). html_hash anchor: first li.product
outer HTML with text + non-class attrs stripped per arch §2.6 BC Stencil
bullet — theme-engine template-stable across Stencil stores.

Test fixture regen path:
  UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 \\
       (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
  curl -sS -A "$UA" 'https://aquasd.com/acropora/?page=1' \\
    > /tmp/aquasd_acropora.html
  # Trim to first 5 <li class="product"> + minimal page shell + pagination
  # marker. See scrapers/tests/test_aquasd_parse.py for the expected fixture
  # shape and the trim-script in /tmp/aquasd_preflight (Session 1 capture).

Pure shared-parser shakedown — no per-vendor overrides. All scrape behavior
inherited from scrapers.common.parse_bigcommerce via the shared run.py
orchestrator. vendors row + scrapers/vendors/aquasd.yaml carry all config;
this module is the hook point where vendor-specific overrides would land
if AquaSD's site shape ever requires them (none anticipated for the
canonical Stencil shakedown).
"""
