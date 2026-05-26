-- CTK-090 Session 1 — AquaSD vendors row (Phase 2 scraper #7).
--
-- Closes the data-side prerequisite for the AquaSD scraper landing in
-- this CTK Session: scrapers/common/run.py:db.fetch_vendor() reads this
-- row at stage 1 (Config) of the arch §2.1 lifecycle, then merges with
-- scrapers/vendors/aquasd.yaml per arch §2.3 (DB row wins on conflict).
-- Without this row, the scraper fails fast at stage 1 — the right shape;
-- loud-failure-not-silent-skip.
--
-- vendor_id=7 disposition per CTK-090 plan §Scope item 8 + CTK-085
-- Session 2 / Session 3 sequential precedent (Battlecorals id=5, Unique
-- Corals id=6). FK joins on vendor_listings.vendor_id = vendors.id are
-- safe; literal hardcodes of vendor_id=7 in matcher / notifier / analytics
-- modules fire the open-items.md L25 vendor-ID stability watch trigger
-- and graduate to INV-03 if a second consumer pattern lands.
--
-- vendors-row columns (per supabase/migrations/0001_init.sql:40-53 schema,
-- extended at 0014_extend_vendors_platform_bigcommerce.sql for the
-- 'bigcommerce' value):
--   - id = 7            smallserial primary key; explicit literal here for
--                       open-items.md L25 vendor-ID stability watch (CTK-028
--                       seed.sql baked Phase 1 ids 1-4 via auto-increment;
--                       Phase 2 per-vendor tickets explicitize the id).
--   - slug = 'aquasd'             matches scrapers/vendors/aquasd.yaml slug
--                                  + .github/workflows/aquasd.yml workflow
--                                  name (run.py CLI arg).
--   - display_name = 'AquaSD'      San Diego CA West Coast must-have per
--                                  .claude/research/phase-1.5-vendor-scan.md
--                                  §6 (amended 2026-05-25 — BigCommerce
--                                  Stencil, not Shopify as original §6
--                                  inferred).
--   - base_url = 'https://aquasd.com'  bare-domain per all-vendor precedent
--                                       (PE/WWC/TSA/JF/BC/UC).
--   - platform = 'bigcommerce'     five-signal pre-flight 2026-05-25/26
--                                   (cite-back in scrapers/vendors/aquasd.yaml).
--                                   Migration 0014 must apply BEFORE this
--                                   INSERT — un-extended CHECK rejects
--                                   'bigcommerce'.
--   - scrape_method = 'html'       BC Stencil category-page HTML scrape via
--                                   scrapers/common/parse_bigcommerce.py
--                                   (decision register row #66). Distinct
--                                   from Shopify's 'products_json' shape.
--   - cadence_label = 'daily'      arch §2.7 decision #15 + CTK-090 plan
--                                   §Scope item 7 cadence lock; daily 03-05
--                                   ET baseline. AquaSD's drop cadence
--                                   doesn't warrant hourly-tier (per phase-
--                                   1.5-vendor-scan §6 cadence indicators).
--   - image_strategy = 'mirror'    default per arch §1.3 + CTK-019 #52;
--                                   runtime-flippable to 'hotlink' on vendor
--                                   pushback via UPDATE (no code commit).
--   - active = true                workflow_dispatch fires immediately; first
--                                   cron firing observed at next 03-05 ET
--                                   boundary (~24h wait max under daily).
--
-- Idempotent re-application: ON CONFLICT (slug) DO NOTHING preserves the row
-- across migration re-runs + supabase db reset cycles. The setval call at
-- the end bumps the smallserial sequence past the explicit-id INSERT so
-- subsequent vendor INSERTs without an explicit id (Phase 2.5+ vendors,
-- e.g. Coral Farm if it lands as a sibling BC vendor) don't collide.
--
-- seed.sql parity note: supabase/seed.sql carries Phase 1 vendors 1-4 only
-- per CTK-028 D3 sub-option (a) ("Phase 2+ vendors deferred to per-vendor
-- tickets"); this migration is the canonical add-path for AquaSD. Dev-side
-- `supabase db reset` runs migrations BEFORE seed.sql, so the AquaSD row
-- lands from this migration; seed.sql's ON CONFLICT preserves it on
-- re-application.

INSERT INTO vendors (id, slug, display_name, base_url, platform, scrape_method, cadence_label, image_strategy, active)
VALUES
  (7, 'aquasd', 'AquaSD', 'https://aquasd.com', 'bigcommerce', 'html', 'daily', 'mirror', true)
ON CONFLICT (slug) DO NOTHING;

-- Bump the smallserial sequence past the explicit-id INSERT so subsequent
-- vendor INSERTs without an explicit id don't collide on id=7 (or the
-- existing id=13 _ctk033_test row which already held the sequence prior
-- to this batch).
SELECT setval(
  pg_get_serial_sequence('vendors', 'id'),
  (SELECT MAX(id) FROM vendors)
);
