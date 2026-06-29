-- CTK-212 Session 1 — Biota (The Biota Group) vendors row (Phase 2 vendor wave;
-- scraper #18).
--
-- Closes the data-side prerequisite for the Biota scraper landing in the same CTK:
-- scrapers/common/run.py db.fetch_vendor() reads this row at stage 1 (Config) of
-- the arch §2.1 lifecycle, then merges with scrapers/vendors/biota.yaml per arch
-- §2.3 (DB row wins on conflict). Without this row the scraper fails fast at stage
-- 1 — the right shape; loud-failure-not-silent-skip.
--
-- vendor_id=65 disposition (NOT 38). The CTK-212 directive proposed id=38 as the
-- "next real-vendor id above coralstop=37" but flagged "verify MAX(id) live before
-- applying". Live verification 2026-06-29: id=38 is TAKEN by '_ctk208_test'
-- (a CTK-208 test row that landed after coralstop=37), and the test rows now reach
-- id=64 ('_ctk208_cadence_test'). MAX(id)=64. An explicit INSERT id=38 would
-- COLLIDE. Per the fleet idiom ("next clean integer above every existing row";
-- 0064 coralstop=37 was chosen when MAX(id) was 36), the collision-free choice is
-- 65 = MAX(id)+1. Real vendors: 1-12, 33-37, 65; test rows (active=false)
-- interleave at 13-16/21-22/32/38/63-64. An explicit literal preserves the
-- open-items.md L25 vendor-ID stability watch. (Verify MAX(id)=64 live before
-- apply; bump to MAX(id)+1 if a vendor row landed since.)
--
-- Slug canon (CTK-044 / CTK-095): public URLs kebab; DB / YAML / R2 paths snake.
-- "biota" is a single lowercase token (no internal separator), identical in kebab
-- and snake — no normalization needed (same single-token shape as coralstop 0064 /
-- reefundertheroof 0063). The slug matches scrapers/vendors/biota.yaml `slug:` +
-- the .github/workflows/biota.yml `python -m scrapers.common.run biota` CLI arg in
-- lock-step. (display_name carries the canonical "The Biota Group".)
--
-- base_url note: the LIVE STORE is shop.thebiotagroup.com (thebiotagroup.com
-- 301-redirects to it; backend biotagroup.myshopify.com). biotaaquariums.com and
-- biota.com are PARKED/dead — the row points at the store domain only.
--
-- vendors-row columns (per supabase/migrations/0001_init.sql schema):
--   - id = 65               smallserial primary key; explicit literal for the
--                           open-items.md L25 vendor-ID stability watch + the
--                           38-collision avoidance above.
--   - slug = 'biota'        matches biota.yaml slug + biota.yml workflow CLI arg.
--   - display_name = "The Biota Group"  100%-aquacultured livestock vendor;
--                           615-product / 3-page catalog (2026-06-29 full walk).
--   - base_url = 'https://shop.thebiotagroup.com'  the live store (NOT the parked
--                           biota.com / biotaaquariums.com); five-signal re-confirm
--                           at build 2026-06-29 (cite-back in biota.yaml).
--   - platform = 'shopify'         five-signal re-confirm 2026-06-29.
--   - scrape_method = 'products_json'  canonical Shopify endpoint shape.
--   - cadence_label = 'hourly'     arch §2.7 decision #15 + Phase 2 vendor-wave
--                                   default (17 * * * * UTC, off-minute per
--                                   open-items.md off-minute discipline).
--   - image_strategy = 'mirror'    default per arch §1.3 + CTK-019 #52;
--                                   runtime-flippable to 'hotlink' via UPDATE.
--   - active = true                workflow_dispatch fires immediately; first
--                                   scheduled cron firing at the next :17 boundary.
--
-- Idempotent re-application: ON CONFLICT (slug) DO NOTHING preserves the row across
-- migration re-runs + supabase db reset cycles.
--
-- seed.sql parity note: supabase/seed.sql carries Phase 1 vendors 1-4 only per
-- CTK-028 D3 sub-option (a); this migration is the canonical add-path for Biota.

INSERT INTO vendors (id, slug, display_name, base_url, platform, scrape_method, cadence_label, image_strategy, active)
VALUES
  (65, 'biota', 'The Biota Group', 'https://shop.thebiotagroup.com', 'shopify', 'products_json', 'hourly', 'mirror', true)
ON CONFLICT (slug) DO NOTHING;

-- Bump the smallserial sequence past the explicit-id INSERT so subsequent vendor
-- INSERTs without an explicit id don't collide. Matches the fleet idiom (0048-0064):
-- resolve the sequence dynamically via pg_get_serial_sequence, set to MAX(id). An
-- explicit-id INSERT does not advance the sequence, so this aligns it with the real
-- max. No-op on re-run.
SELECT setval(
  pg_get_serial_sequence('vendors', 'id'),
  (SELECT MAX(id) FROM vendors)
);
