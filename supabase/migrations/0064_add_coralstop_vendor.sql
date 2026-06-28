-- CTK-209 Session 1 — Coral Stop vendors row (Phase 2 vendor wave; scraper #17).
--
-- Closes the data-side prerequisite for the Coral Stop scraper landing in the same
-- CTK: scrapers/common/run.py db.fetch_vendor() reads this row at stage 1 (Config)
-- of the arch §2.1 lifecycle, then merges with scrapers/vendors/coralstop.yaml per
-- arch §2.3 (DB row wins on conflict). Without this row the scraper fails fast at
-- stage 1 — the right shape; loud-failure-not-silent-skip.
--
-- vendor_id=37 disposition: the next clean integer above every existing row —
-- williamsons id=33 (0059), reefregeneration id=34 (0060), austinaquafarms id=35
-- (0061), reefundertheroof id=36 (0063), so 37 is the next free real-vendor id
-- above the interleaved _ctkNNN_test rows. Live verification 2026-06-28:
-- MAX(id)=36, slug 'coralstop' absent. An explicit literal preserves the
-- open-items.md L25 vendor-ID stability watch. Collision-free, leaves the test rows
-- untouched. FK joins on vendor_listings.vendor_id = vendors.id are safe; literal
-- hardcodes of vendor_id=37 in matcher / notifier / analytics modules fire the
-- open-items.md L25 vendor-ID stability watch trigger. (Verify MAX(id)=36 live
-- before apply; bump to MAX(id)+1 if a vendor row landed between 0063 and here.)
--
-- Slug canon (CTK-044 / CTK-095): public URLs kebab; DB / YAML / R2 paths snake.
-- "coralstop" is a single lowercase token (no internal separator, matching the
-- coralstop.com domain), so it is identical in kebab and snake — no normalization
-- needed (same single-token shape as reefundertheroof 0063 / austinaquafarms 0061).
-- The slug matches scrapers/vendors/coralstop.yaml `slug:` + the
-- .github/workflows/coralstop.yml `python -m scrapers.common.run coralstop` CLI arg
-- in lock-step. (display_name carries the canonical "Coral Stop".)
--
-- vendors-row columns (per supabase/migrations/0001_init.sql schema):
--   - id = 37               smallserial primary key; explicit literal here for the
--                           open-items.md L25 vendor-ID stability watch.
--   - slug = 'coralstop'    matches coralstop.yaml slug + coralstop.yml workflow
--                           CLI arg (run.py <slug>).
--   - display_name = "Coral Stop"  Shopify frag-house reseller; deep multi-page
--                           catalog (939 rows, 4 pages, 2026-06-28 walk).
--   - base_url = 'https://coralstop.com'  canonical public domain (five-signal
--                           re-confirm at build 2026-06-28).
--   - platform = 'shopify'         five-signal re-confirm 2026-06-28 (cite-back in
--                                   scrapers/vendors/coralstop.yaml).
--   - scrape_method = 'products_json'  canonical Shopify endpoint shape.
--   - cadence_label = 'hourly'     arch §2.7 decision #15 + Phase 2 vendor-wave
--                                   default (49 * * * * UTC, off-minute per
--                                   open-items.md off-minute discipline).
--   - image_strategy = 'mirror'    default per arch §1.3 + CTK-019 #52;
--                                   runtime-flippable to 'hotlink' on vendor
--                                   pushback via UPDATE (no code commit).
--   - active = true                workflow_dispatch fires immediately; first
--                                   scheduled cron firing at the next :49 boundary
--                                   (~60-min wait max under hourly cadence).
--
-- Idempotent re-application: ON CONFLICT (slug) DO NOTHING preserves the row across
-- migration re-runs + supabase db reset cycles.
--
-- seed.sql parity note: supabase/seed.sql carries Phase 1 vendors 1-4 only per
-- CTK-028 D3 sub-option (a) ("Phase 2+ vendors deferred to per-vendor tickets");
-- this migration is the canonical add-path for Coral Stop. Dev-side
-- `supabase db reset` runs migrations BEFORE seed.sql, so the Coral Stop row lands
-- from this migration.

INSERT INTO vendors (id, slug, display_name, base_url, platform, scrape_method, cadence_label, image_strategy, active)
VALUES
  (37, 'coralstop', 'Coral Stop', 'https://coralstop.com', 'shopify', 'products_json', 'hourly', 'mirror', true)
ON CONFLICT (slug) DO NOTHING;

-- Bump the smallserial sequence past the explicit-id INSERT so subsequent vendor
-- INSERTs without an explicit id don't collide. Matches the fleet idiom (0048
-- Cornbred / 0059 Williamson's / 0060 Reef Regeneration / 0061 Austin Aqua Farms /
-- 0063 Reef Under The Roof): resolve the sequence dynamically via
-- pg_get_serial_sequence, set to MAX(id). An explicit-id INSERT does not advance
-- the sequence, so this aligns it with the real max. No-op on re-run. Plain MAX(id)
-- setval — not a GREATEST guard (fleet idiom).
SELECT setval(
  pg_get_serial_sequence('vendors', 'id'),
  (SELECT MAX(id) FROM vendors)
);
