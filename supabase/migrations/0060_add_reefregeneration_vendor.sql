-- CTK-148 Session 1 — Reef Regeneration vendors row (Phase 2 vendor wave,
-- R2R sponsor-roster discovery; scraper #14).
--
-- Closes the data-side prerequisite for the Reef Regeneration scraper landing in
-- the same CTK: scrapers/common/run.py db.fetch_vendor() reads this row at stage
-- 1 (Config) of the arch §2.1 lifecycle, then merges with
-- scrapers/vendors/reefregeneration.yaml per arch §2.3 (DB row wins on
-- conflict). Without this row the scraper fails fast at stage 1 — the right
-- shape; loud-failure-not-silent-skip.
--
-- vendor_id=34 disposition: derived LIVE 2026-06-28 — MAX(id)=33 (williamsons,
-- migration 0059), so 34 is the next clean integer above every existing row.
-- The contiguous real-vendor block (1-12) ended when _ctkNNN_test rows
-- interleaved at 13+ (live observation 2026-06-28: 13 _ctk033_test, 14
-- _ctk029_test, 15 _ctk100_test, 16 _ctk032_test, 21 _ctk124_test, 22
-- _ctk137_test, 32 _ctk042_test, 33 williamsons). An explicit literal here
-- preserves the open-items.md L25 vendor-ID stability watch. Collision-free,
-- leaves the test rows untouched. FK joins on vendor_listings.vendor_id =
-- vendors.id are safe; literal hardcodes of vendor_id=34 in matcher / notifier /
-- analytics modules fire the open-items.md L25 vendor-ID stability watch trigger.
--
-- Slug canon (CTK-044 / CTK-095): public URLs kebab; DB / YAML / R2 paths snake.
-- "reefregeneration" is a single lowercase token (no internal separator), so it
-- is identical in kebab and snake — no normalization needed. The slug matches
-- scrapers/vendors/reefregeneration.yaml `slug:` + the .github/workflows/
-- reefregeneration.yml `python -m scrapers.common.run reefregeneration` CLI arg
-- in lock-step. (display_name carries the canonical "Reef Regeneration".)
--
-- vendors-row columns (per supabase/migrations/0001_init.sql schema):
--   - id = 34               smallserial primary key; explicit literal here for
--                           the open-items.md L25 vendor-ID stability watch.
--   - slug = 'reefregeneration'  matches reefregeneration.yaml slug +
--                           reefregeneration.yml workflow CLI arg (run.py <slug>).
--   - display_name = "Reef Regeneration"  R2R sponsor-roster reseller+house;
--                           best-categorized target of the 2026-06-12 mine.
--   - base_url = 'https://reefregeneration.com'  canonical public domain
--                           (five-signal re-confirm at build 2026-06-28).
--   - platform = 'shopify'         five-signal re-confirm 2026-06-28 (cite-back
--                                   in scrapers/vendors/reefregeneration.yaml).
--   - scrape_method = 'products_json'  canonical Shopify endpoint shape.
--   - cadence_label = 'hourly'     arch §2.7 decision #15 + Phase 2 vendor-wave
--                                   default (25 * * * * UTC, off-minute per
--                                   open-items.md off-minute discipline).
--   - image_strategy = 'mirror'    default per arch §1.3 + CTK-019 #52;
--                                   runtime-flippable to 'hotlink' on vendor
--                                   pushback via UPDATE (no code commit).
--   - active = true                workflow_dispatch fires immediately; first
--                                   scheduled cron firing at the next :25
--                                   boundary (~60-min wait max under hourly
--                                   cadence).
--
-- Idempotent re-application: ON CONFLICT (slug) DO NOTHING preserves the row
-- across migration re-runs + supabase db reset cycles.
--
-- seed.sql parity note: supabase/seed.sql carries Phase 1 vendors 1-4 only per
-- CTK-028 D3 sub-option (a) ("Phase 2+ vendors deferred to per-vendor tickets");
-- this migration is the canonical add-path for Reef Regeneration. Dev-side
-- `supabase db reset` runs migrations BEFORE seed.sql, so the RR row lands from
-- this migration.

INSERT INTO vendors (id, slug, display_name, base_url, platform, scrape_method, cadence_label, image_strategy, active)
VALUES
  (34, 'reefregeneration', 'Reef Regeneration', 'https://reefregeneration.com', 'shopify', 'products_json', 'hourly', 'mirror', true)
ON CONFLICT (slug) DO NOTHING;

-- Bump the smallserial sequence past the explicit-id INSERT so subsequent vendor
-- INSERTs without an explicit id don't collide. Matches the fleet idiom (0048
-- Cornbred / 0059 Williamson's): resolve the sequence dynamically via
-- pg_get_serial_sequence, set to MAX(id). An explicit-id INSERT does not advance
-- the sequence, so this aligns it with the real max. No-op on re-run. Plain
-- MAX(id) setval — not a GREATEST guard (fleet idiom per 0059's SQL body).
SELECT setval(
  pg_get_serial_sequence('vendors', 'id'),
  (SELECT MAX(id) FROM vendors)
);
