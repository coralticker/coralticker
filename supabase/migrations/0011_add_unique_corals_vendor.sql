-- CTK-085 Session 3 — Unique Corals vendors row (Phase 2 scraper #6).
--
-- Closes the data-side prerequisite for the Unique Corals scraper landing in
-- the same CTK Session: scrapers/common/run.py:db.fetch_vendor() reads this
-- row at stage 1 (Config) of the arch §2.1 lifecycle, then merges with
-- scrapers/vendors/unique_corals.yaml per arch §2.3 (DB row wins on
-- conflict). Without this row, the scraper fails fast at stage 1 — the
-- right shape; loud-failure-not-silent-skip.
--
-- vendor_id=6 disposition per CTK-085 plan §Scope L64 + Session 2 D5
-- precedent (Battlecorals vendor_id=5 explicit-id continuation from JF=4).
-- Phase 1 baked ids 1-4 via auto-increment seed (PE / WWC / TSA / JF);
-- Battlecorals migration 0010 added id=5; UC continues sequential at id=6.
-- FK joins on vendor_listings.vendor_id = vendors.id are safe; literal
-- hardcodes of vendor_id=6 in matcher / notifier / analytics modules fire
-- the open-items.md L25 watch trigger and graduate to INV-03 if a second
-- consumer pattern lands.
--
-- Vendor-ID gap acknowledgement (CTK-085 Session 2 Q-3 disposition):
-- _ctk033_test test row at id=13 holds the smallserial sequence at
-- last_value=13 prior to this migration. UC explicit-id=6 INSERT continues
-- sequential per directive Q-3 disposition (accept-the-gap path); future
-- CTK-086/087/088 vendors land at id=14+ via setval bump at the end of this
-- migration. id range 7-12 remains unused (acceptable; FK joins don't care
-- about gaps).
--
-- vendors-row columns (per supabase/migrations/0001_init.sql:40-53 schema):
--   - id = 6            smallserial primary key; explicit literal here for
--                       open-items.md L25 vendor-ID stability watch (CTK-028
--                       seed.sql baked Phase 1 ids 1-4 via auto-increment;
--                       Phase 2 per-vendor tickets explicitize the id).
--   - slug = 'unique-corals'       matches scrapers/vendors/unique_corals.yaml
--                                   slug + .github/workflows/unique-corals.yml
--                                   workflow name (run.py CLI arg).
--   - display_name = 'Unique Corals' Los Angeles CA West Coast must-have per
--                                     .claude/research/phase-1.5-vendor-scan.md
--                                     §5
--   - base_url = 'https://uniquecorals.com'  bare-domain per all-vendor
--                                             precedent (PE/WWC/TSA/JF/
--                                             Battlecorals); Shopify-side
--                                             canonical_host_redirection
--                                             enforces bare from www.
--   - platform = 'shopify'         five-signal pre-flight 2026-05-25 (cite-back
--                                   in scrapers/vendors/unique_corals.yaml)
--   - scrape_method = 'products_json'  canonical Shopify endpoint shape
--   - cadence_label = 'hourly'     arch §2.7 decision #15 + CTK-085 plan §Scope
--                                   cadence lock (29 * * * * UTC, off-minute
--                                   per open-items.md L53 discipline); Q-2
--                                   disposition hourly-only v1, Phase 2.5
--                                   overlay CTK deferred-with-trigger
--   - image_strategy = 'mirror'    default per arch §1.3 + CTK-019 #52;
--                                   runtime-flippable to 'hotlink' on vendor
--                                   pushback via UPDATE (no code commit)
--   - active = true                workflow_dispatch fires immediately; first
--                                   cron firing observed at next :29 boundary
--                                   (~60-min wait max under hourly cadence)
--
-- Idempotent re-application: ON CONFLICT (slug) DO NOTHING preserves the row
-- across migration re-runs + supabase db reset cycles. The setval call at
-- the end bumps the smallserial sequence past the explicit-id INSERT so
-- subsequent vendor INSERTs without an explicit id (Phase 2.5+ vendors,
-- CTK-086 / CTK-087 / CTK-088 follow-ons) don't collide.
--
-- seed.sql parity note: supabase/seed.sql carries Phase 1 vendors 1-4 only
-- per CTK-028 D3 sub-option (a) ("Phase 2+ vendors deferred to per-vendor
-- tickets"); this migration is the canonical add-path for Unique Corals.
-- Dev-side `supabase db reset` runs migrations BEFORE seed.sql, so the
-- Unique Corals row lands from this migration; seed.sql's ON CONFLICT
-- preserves it on re-application.

INSERT INTO vendors (id, slug, display_name, base_url, platform, scrape_method, cadence_label, image_strategy, active)
VALUES
  (6, 'unique-corals', 'Unique Corals', 'https://uniquecorals.com', 'shopify', 'products_json', 'hourly', 'mirror', true)
ON CONFLICT (slug) DO NOTHING;

-- Bump the smallserial sequence past the explicit-id INSERT so subsequent
-- vendor INSERTs without an explicit id don't collide on id=6 (or the
-- existing id=13 _ctk033_test row which already holds the sequence).
SELECT setval(
  pg_get_serial_sequence('vendors', 'id'),
  (SELECT MAX(id) FROM vendors)
);
