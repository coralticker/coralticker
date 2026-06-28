-- CTK-146 Session 1 — Williamson's Reef vendors row (Phase 2 vendor wave,
-- R2R sponsor-roster discovery; scraper #13).
--
-- Closes the data-side prerequisite for the Williamson's scraper landing in the
-- same CTK: scrapers/common/run.py db.fetch_vendor() reads this row at stage 1
-- (Config) of the arch §2.1 lifecycle, then merges with
-- scrapers/vendors/williamsons.yaml per arch §2.3 (DB row wins on conflict).
-- Without this row the scraper fails fast at stage 1 — the right shape;
-- loud-failure-not-silent-skip.
--
-- vendor_id=33 disposition: the contiguous real-vendor block (1-12) is FULL
-- after Cornbred took id=12 (migration 0048). id=13 onward are _ctkNNN_test
-- rows (live observation 2026-06-28: 13 _ctk033_test, 14 _ctk029_test,
-- 15 _ctk100_test, 16 _ctk032_test, 21 _ctk124_test, 22 _ctk137_test,
-- 32 _ctk042_test; MAX(id)=32). The directive's "next id = 13" assumption is
-- contradicted by reality — 13 is occupied, so an explicit INSERT id=13 would
-- collide on the primary key (ON CONFLICT (slug) would NOT catch it). id=33 is
-- the next clean integer above every existing row: collision-free, leaves the
-- test rows untouched, and preserves the explicit-literal posture for the
-- open-items.md L25 vendor-ID stability watch (CTK-146 #2, Jon-approved
-- 2026-06-28). The "real vendors contiguous" nicety already ended when test
-- rows interleaved at 13+; chasing it via gap-reuse (e.g. id=17) would be more
-- confusing, not less. FK joins on vendor_listings.vendor_id = vendors.id are
-- safe; literal hardcodes of vendor_id=33 in matcher / notifier / analytics
-- modules fire the open-items.md L25 vendor-ID stability watch trigger.
--
-- Slug canon (CTK-044 / CTK-095): public URLs kebab; DB / YAML / R2 paths
-- snake. Williamson's is a single-token vendor, so slug 'williamsons' is
-- unambiguous (no kebab->snake normalization needed). The slug matches
-- scrapers/vendors/williamsons.yaml `slug:` + the .github/workflows/
-- williamsons.yml `python -m scrapers.common.run williamsons` CLI arg in
-- lock-step. (Apostrophe dropped from the brand name for a clean ASCII slug;
-- display_name carries the canonical "Williamson's Reef".)
--
-- vendors-row columns (per supabase/migrations/0001_init.sql schema):
--   - id = 33               smallserial primary key; explicit literal here for
--                           the open-items.md L25 vendor-ID stability watch.
--   - slug = 'williamsons'  matches williamsons.yaml slug + williamsons.yml
--                           workflow CLI arg (run.py <slug>).
--   - display_name = "Williamson's Reef"  R2R Gold-sponsor reseller; cleanest
--                           target of the 2026-06-12 sponsor-roster mine.
--   - base_url = 'https://williamsonsreef.com'  canonical public domain
--                           (five-signal re-confirm at build 2026-06-28).
--   - platform = 'shopify'         five-signal re-confirm 2026-06-28 (cite-back
--                                   in scrapers/vendors/williamsons.yaml).
--   - scrape_method = 'products_json'  canonical Shopify endpoint shape.
--   - cadence_label = 'hourly'     arch §2.7 decision #15 + Phase 2 vendor-wave
--                                   default (33 * * * * UTC, off-minute per
--                                   open-items.md off-minute discipline).
--   - image_strategy = 'mirror'    default per arch §1.3 + CTK-019 #52;
--                                   runtime-flippable to 'hotlink' on vendor
--                                   pushback via UPDATE (no code commit).
--   - active = true                workflow_dispatch fires immediately; first
--                                   scheduled cron firing at the next :33
--                                   boundary (~60-min wait max under hourly
--                                   cadence).
--
-- Idempotent re-application: ON CONFLICT (slug) DO NOTHING preserves the row
-- across migration re-runs + supabase db reset cycles.
--
-- seed.sql parity note: supabase/seed.sql carries Phase 1 vendors 1-4 only per
-- CTK-028 D3 sub-option (a) ("Phase 2+ vendors deferred to per-vendor
-- tickets"); this migration is the canonical add-path for Williamson's. Dev-side
-- `supabase db reset` runs migrations BEFORE seed.sql, so the Williamson's row
-- lands from this migration.

INSERT INTO vendors (id, slug, display_name, base_url, platform, scrape_method, cadence_label, image_strategy, active)
VALUES
  (33, 'williamsons', 'Williamson''s Reef', 'https://williamsonsreef.com', 'shopify', 'products_json', 'hourly', 'mirror', true)
ON CONFLICT (slug) DO NOTHING;

-- Bump the smallserial sequence past the explicit-id INSERT so subsequent
-- vendor INSERTs without an explicit id don't collide. Matches the fleet idiom
-- (0048 Cornbred et al.): resolve the sequence dynamically via
-- pg_get_serial_sequence, set to MAX(id). An explicit-id INSERT does not advance
-- the sequence, so this aligns it with the real max. No-op on re-run.
SELECT setval(
  pg_get_serial_sequence('vendors', 'id'),
  (SELECT MAX(id) FROM vendors)
);
