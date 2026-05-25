-- CTK-085 Session 2 — Battlecorals vendors row (Phase 2 scraper #5).
--
-- Closes the data-side prerequisite for the Battlecorals scraper landing in
-- the same CTK Session: scrapers/common/run.py:db.fetch_vendor() reads this
-- row at stage 1 (Config) of the arch §2.1 lifecycle, then merges with
-- scrapers/vendors/battlecorals.yaml per arch §2.3 (DB row wins on
-- conflict). Without this row, the scraper fails fast at stage 1 — the
-- right shape; loud-failure-not-silent-skip.
--
-- vendor_id=5 disposition per CTK-085 plan §Scope L62 + .claude/open-items.md
-- L25 vendor-ID stability watch. AquaSD split to CTK-090 at Session 1c
-- 2026-05-25 vacated the originally-planned-vendor_id=5 slot; Battlecorals
-- inherits the slot per directive Q-3 re-disposition. FK joins on
-- vendor_listings.vendor_id = vendors.id are safe; literal hardcodes of
-- vendor_id=5 in matcher / notifier / analytics modules fire the L25 watch
-- trigger and graduate to INV-03 if a second consumer pattern lands.
--
-- vendors-row columns (per supabase/migrations/0001_init.sql:40-53 schema):
--   - id = 5            smallserial primary key; explicit literal here for
--                       L25 vendor-ID stability watch (CTK-028 seed.sql
--                       baked Phase 1 ids 1-4 via auto-increment; Phase 2
--                       per-vendor tickets explicitize the id).
--   - slug = 'battlecorals'        matches scrapers/vendors/battlecorals.yaml
--   - display_name = 'Battlecorals' Austin TX SPS-strong vendor per
--                                   .claude/research/phase-1.5-vendor-scan.md §4
--   - base_url = 'https://battlecorals.com'
--   - platform = 'shopify'         five-signal pre-flight 2026-05-25 (cite-back
--                                   in scrapers/vendors/battlecorals.yaml)
--   - scrape_method = 'products_json'  canonical Shopify endpoint shape
--   - cadence_label = 'daily'      arch §2.7 decision #15 + CTK-085 plan §Scope
--                                   cadence lock (23 8 * * * UTC)
--   - image_strategy = 'mirror'    default per arch §1.3 + CTK-019 #52;
--                                   runtime-flippable to 'hotlink' on vendor
--                                   pushback via UPDATE (no code commit)
--   - active = true                workflow_dispatch fires immediately; first
--                                   cron firing observed at 8:23 UTC next cycle
--
-- Idempotent re-application: ON CONFLICT (slug) DO NOTHING preserves the row
-- across migration re-runs + supabase db reset cycles. The setval call at
-- the end bumps the smallserial sequence past the explicit-id INSERT so
-- subsequent vendor INSERTs without an explicit id (Phase 2.5+ vendors,
-- CTK-086 / CTK-087 / CTK-088 follow-ons) don't collide.
--
-- seed.sql parity note: supabase/seed.sql carries Phase 1 vendors 1-4 only
-- per CTK-028 D3 sub-option (a) ("Phase 2+ vendors deferred to per-vendor
-- tickets"); this migration is the canonical add-path for Battlecorals.
-- Dev-side `supabase db reset` runs migrations BEFORE seed.sql, so the
-- Battlecorals row lands from this migration; seed.sql's ON CONFLICT
-- preserves it on re-application.

INSERT INTO vendors (id, slug, display_name, base_url, platform, scrape_method, cadence_label, image_strategy, active)
VALUES
  (5, 'battlecorals', 'Battlecorals', 'https://battlecorals.com', 'shopify', 'products_json', 'daily', 'mirror', true)
ON CONFLICT (slug) DO NOTHING;

-- Bump the smallserial sequence past the explicit-id INSERT so subsequent
-- vendor INSERTs without an explicit id don't collide on id=5.
SELECT setval(
  pg_get_serial_sequence('vendors', 'id'),
  (SELECT MAX(id) FROM vendors)
);
