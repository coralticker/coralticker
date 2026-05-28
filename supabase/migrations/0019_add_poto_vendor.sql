-- CTK-088 — POTO (Pieces of the Ocean) vendors row (Phase 2 scraper #10).
--
-- Closes the data-side prerequisite for the POTO scraper: scrapers/common/
-- run.py:db.fetch_vendor() reads this row at stage 1 (Config) of the arch
-- §2.1 lifecycle, then merges with scrapers/vendors/poto.yaml per arch §2.3
-- (DB row wins on conflict). Without this row, the scraper fails fast at
-- stage 1 — loud-failure-not-silent-skip.
--
-- vendor_id=10 disposition per CTK-088 plan §Scope item 4 + sequential
-- precedent (Battlecorals 5, Unique Corals 6, AquaSD 7, Vivid 8, Reef
-- Chasers 9). id=10 is the next contiguous Phase 2 explicit-id; Tidal
-- Gardens is reserved at 11 (CTK-087). FK joins on vendor_listings.vendor_id
-- = vendors.id are safe; literal hardcodes of vendor_id=10 in matcher /
-- notifier / analytics modules fire the open-items.md L25 vendor-ID
-- stability watch trigger and graduate to INV-03 if a second consumer
-- pattern lands.
--
-- Sequence + collision check (CTK-088 impl, confirmed on Neon 2026-05-28):
-- MAX(vendors.id) = 14. Real vendors occupy 1-9; test rows hold the tail
-- (_ctk033_test id=13, _ctk029_test id=14). The smallserial sequence sits
-- at 14. id range 10-12 is UNUSED — so the explicit id=10 INSERT is
-- collision-free, and the trailing setval is a no-op (id=10 < MAX 14 →
-- setval(MAX(id)) leaves the sequence at 14). This reconciles the
-- _ctk029_test@14 holder confirmed at CTK-086 Session 3 (prior migration
-- comments 0010/0011/0015/0017 said _ctk033_test@13; both test rows exist,
-- 13 and 14, MAX is 14).
--
-- vendors-row columns (per supabase/migrations/0001_init.sql:40-53 schema):
--   - id = 10           smallserial primary key; explicit literal for
--                       open-items.md L25 vendor-ID stability watch.
--   - slug = 'poto'               matches scrapers/vendors/poto.yaml slug +
--                                  .github/workflows/poto.yml workflow name
--                                  (run.py CLI arg).
--   - display_name = 'Pieces of the Ocean'  New York, NY per .claude/
--                                            research/phase-1.5-vendor-scan.md
--                                            §10.
--   - base_url = 'https://piecesoftheocean.com'  canonical domain (homepage
--                                                  301s to itself; the
--                                                  Shopify shop slug is
--                                                  piecesoftheocean.myshopify.com).
--   - platform = 'shopify'        five-signal pre-flight 2026-05-28
--                                  (powered-by: Shopify header; cite-back in
--                                  scrapers/vendors/poto.yaml).
--   - scrape_method = 'products_json'  canonical Shopify endpoint shape.
--   - cadence_label = 'hourly'    arch §2.7 decision #15 + CTK-088 plan §Q2
--                                  cadence lock (53 * * * * UTC, off-minute
--                                  per open-items.md L53). POTO runs timed
--                                  live-sale drops; latency matters.
--   - image_strategy = 'mirror'   default per arch §1.3 + CTK-019 #52;
--                                  runtime-flippable to 'hotlink' via UPDATE.
--   - active = true               workflow_dispatch fires immediately; first
--                                  scheduled cron firing at next :53 boundary.
--
-- NOTE on what this scraper captures (coordination): POTO Shopify =
-- current-buyable live-sale coral capture (in_stock_only gate keeps ~164
-- buyable of a 5,466-row permanent archive). POTO's auction-side capture is
-- ReefnBid (CTK-007, parked Tier 4) — NOT this row. The two are not merged
-- into one vendor_listings row (CTK-007 decision #69).
--
-- Idempotent re-application: ON CONFLICT (slug) DO NOTHING preserves the row
-- across migration re-runs + supabase db reset cycles.
--
-- seed.sql parity note: supabase/seed.sql carries Phase 1 vendors 1-4 only
-- per CTK-028 D3 sub-option (a); this migration is the canonical add-path
-- for POTO. Dev-side `supabase db reset` runs migrations BEFORE seed.sql,
-- so the POTO row lands from this migration; seed.sql's ON CONFLICT
-- preserves it on re-application.

INSERT INTO vendors (id, slug, display_name, base_url, platform, scrape_method, cadence_label, image_strategy, active)
VALUES
  (10, 'poto', 'Pieces of the Ocean', 'https://piecesoftheocean.com', 'shopify', 'products_json', 'hourly', 'mirror', true)
ON CONFLICT (slug) DO NOTHING;

-- Bump the smallserial sequence past the explicit-id INSERT so subsequent
-- vendor INSERTs without an explicit id don't collide on id=10. No-op under
-- current sequence state (MAX(id)=14 from _ctk029_test; id=10 < 14).
SELECT setval(
  pg_get_serial_sequence('vendors', 'id'),
  (SELECT MAX(id) FROM vendors)
);
