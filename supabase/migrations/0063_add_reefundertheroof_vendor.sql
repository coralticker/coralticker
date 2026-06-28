-- CTK-207 Session 1 — Reef Under The Roof vendors row (Phase 2 vendor wave,
-- IG-inbound discovery; scraper #16).
--
-- Closes the data-side prerequisite for the Reef Under The Roof scraper landing in
-- the same CTK: scrapers/common/run.py db.fetch_vendor() reads this row at stage
-- 1 (Config) of the arch §2.1 lifecycle, then merges with
-- scrapers/vendors/reefundertheroof.yaml per arch §2.3 (DB row wins on conflict).
-- Without this row the scraper fails fast at stage 1 — the right shape;
-- loud-failure-not-silent-skip.
--
-- vendor_id=36 disposition: the next clean integer above every existing row —
-- williamsons id=33 (0059), reefregeneration id=34 (0060), austinaquafarms id=35
-- (0061), so 36 is the next free real-vendor id above the interleaved _ctkNNN_test
-- rows (13-32 per live observation 2026-06-28: MAX(id)=35, slug 'reefundertheroof'
-- absent). An explicit literal preserves the open-items.md L25 vendor-ID stability
-- watch. Collision-free, leaves the test rows untouched. FK joins on
-- vendor_listings.vendor_id = vendors.id are safe; literal hardcodes of
-- vendor_id=36 in matcher / notifier / analytics modules fire the open-items.md
-- L25 vendor-ID stability watch trigger. (Verify MAX(id)=35 live before apply;
-- bump to MAX(id)+1 if a vendor row landed between 0062 and here.)
--
-- Slug canon (CTK-044 / CTK-095): public URLs kebab; DB / YAML / R2 paths snake.
-- "reefundertheroof" is a single lowercase token (no internal separator, matching
-- the reefundertheroof.com domain), so it is identical in kebab and snake — no
-- normalization needed (same single-token shape as austinaquafarms 0061 /
-- reefregeneration 0060). The slug matches scrapers/vendors/reefundertheroof.yaml
-- `slug:` + the .github/workflows/reefundertheroof.yml `python -m
-- scrapers.common.run reefundertheroof` CLI arg in lock-step. (display_name
-- carries the canonical "Reef Under The Roof".)
--
-- vendors-row columns (per supabase/migrations/0001_init.sql schema):
--   - id = 36               smallserial primary key; explicit literal here for
--                           the open-items.md L25 vendor-ID stability watch.
--   - slug = 'reefundertheroof'  matches reefundertheroof.yaml slug +
--                           reefundertheroof.yml workflow CLI arg (run.py <slug>).
--   - display_name = "Reef Under The Roof"  IG-inbound homegrown-frag house
--                           (Chicago IL); small single-page catalog (82 rows,
--                           1 page, 2026-06-28 walk).
--   - base_url = 'https://reefundertheroof.com'  canonical public domain
--                           (five-signal re-confirm at build 2026-06-28).
--   - platform = 'shopify'         five-signal re-confirm 2026-06-28 (cite-back
--                                   in scrapers/vendors/reefundertheroof.yaml).
--   - scrape_method = 'products_json'  canonical Shopify endpoint shape.
--   - cadence_label = 'hourly'     arch §2.7 decision #15 + Phase 2 vendor-wave
--                                   default (21 * * * * UTC, off-minute per
--                                   open-items.md off-minute discipline).
--   - image_strategy = 'mirror'    default per arch §1.3 + CTK-019 #52;
--                                   runtime-flippable to 'hotlink' on vendor
--                                   pushback via UPDATE (no code commit).
--   - active = true                workflow_dispatch fires immediately; first
--                                   scheduled cron firing at the next :21
--                                   boundary (~60-min wait max under hourly
--                                   cadence).
--
-- Idempotent re-application: ON CONFLICT (slug) DO NOTHING preserves the row
-- across migration re-runs + supabase db reset cycles.
--
-- seed.sql parity note: supabase/seed.sql carries Phase 1 vendors 1-4 only per
-- CTK-028 D3 sub-option (a) ("Phase 2+ vendors deferred to per-vendor tickets");
-- this migration is the canonical add-path for Reef Under The Roof. Dev-side
-- `supabase db reset` runs migrations BEFORE seed.sql, so the RUTR row lands from
-- this migration.

INSERT INTO vendors (id, slug, display_name, base_url, platform, scrape_method, cadence_label, image_strategy, active)
VALUES
  (36, 'reefundertheroof', 'Reef Under The Roof', 'https://reefundertheroof.com', 'shopify', 'products_json', 'hourly', 'mirror', true)
ON CONFLICT (slug) DO NOTHING;

-- Bump the smallserial sequence past the explicit-id INSERT so subsequent vendor
-- INSERTs without an explicit id don't collide. Matches the fleet idiom (0048
-- Cornbred / 0059 Williamson's / 0060 Reef Regeneration / 0061 Austin Aqua
-- Farms): resolve the sequence dynamically via pg_get_serial_sequence, set to
-- MAX(id). An explicit-id INSERT does not advance the sequence, so this aligns it
-- with the real max. No-op on re-run. Plain MAX(id) setval — not a GREATEST guard
-- (fleet idiom).
SELECT setval(
  pg_get_serial_sequence('vendors', 'id'),
  (SELECT MAX(id) FROM vendors)
);
