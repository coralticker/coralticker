-- CTK-086 Session 2 — Vivid Aquariums vendors row (Phase 2 scraper #8).
--
-- Closes the data-side prerequisite for the Vivid Aquariums scraper landing
-- in the same CTK Session: scrapers/common/run.py:db.fetch_vendor() reads
-- this row at stage 1 (Config) of the arch §2.1 lifecycle, then merges
-- with scrapers/vendors/vivid_aquariums.yaml per arch §2.3 (DB row wins
-- on conflict). Without this row, the scraper fails fast at stage 1 — the
-- right shape; loud-failure-not-silent-skip.
--
-- vendor_id=8 disposition per CTK-086 plan §Scope item 4 + CTK-085 Session 2
-- / Session 3 + CTK-090 Session 1 sequential precedent (Battlecorals id=5,
-- Unique Corals id=6, AquaSD id=7). FK joins on vendor_listings.vendor_id =
-- vendors.id are safe; literal hardcodes of vendor_id=8 in matcher /
-- notifier / analytics modules fire the open-items.md L25 vendor-ID
-- stability watch trigger and graduate to INV-03 if a second consumer
-- pattern lands.
--
-- Vendor-ID gap acknowledgement (CTK-085 Session 2 Q-3 disposition
-- inherited): _ctk033_test test row at id=13 holds the smallserial
-- sequence at last_value=13 prior to this migration. Vivid explicit-
-- id=8 INSERT continues sequential per Q-3 accept-the-gap path; future
-- CTK-086 Session 3 (Reef Chasers id=9) + CTK-088 (POTO id=10) +
-- CTK-087 (Tidal Gardens id=11) vendors land at id 9/10/11 with setval
-- no-op under _ctk033_test max=13. id range remains contiguous in the
-- 5-12 explicit Phase 2 block; _ctk033_test continues to hold the
-- sequence until the explicit-id block reaches id=13.
--
-- vendors-row columns (per supabase/migrations/0001_init.sql:40-53 schema):
--   - id = 8            smallserial primary key; explicit literal here for
--                       open-items.md L25 vendor-ID stability watch (CTK-028
--                       seed.sql baked Phase 1 ids 1-4 via auto-increment;
--                       Phase 2 per-vendor tickets explicitize the id).
--   - slug = 'vivid-aquariums'    matches scrapers/vendors/vivid_aquariums.yaml
--                                  slug + .github/workflows/vivid-aquariums.yml
--                                  workflow name (run.py CLI arg).
--   - display_name = 'Vivid Aquariums'  Canoga Park CA established WYSIWYG
--                                        vendor per .claude/research/phase-
--                                        1.5-vendor-scan.md §9.
--   - base_url = 'https://vividaquariums.com'  bare-domain per all-vendor
--                                               precedent (PE/WWC/TSA/JF/
--                                               Battlecorals/UC/AquaSD).
--   - platform = 'shopify'         five-signal pre-flight 2026-05-27 (cite-
--                                   back in scrapers/vendors/vivid_aquariums.yaml)
--   - scrape_method = 'products_json'  canonical Shopify endpoint shape
--   - cadence_label = 'hourly'     arch §2.7 decision #15 + CTK-086 plan
--                                   §Decisions Q-3 cadence lock (19 * * * *
--                                   UTC, off-minute per open-items.md L53 +
--                                   L60 discipline)
--   - image_strategy = 'mirror'    default per arch §1.3 + CTK-019 #52;
--                                   runtime-flippable to 'hotlink' on vendor
--                                   pushback via UPDATE (no code commit)
--   - active = true                workflow_dispatch fires immediately; first
--                                   scheduled cron firing observed at next
--                                   :19 boundary (~60-min wait max under
--                                   hourly cadence)
--
-- Idempotent re-application: ON CONFLICT (slug) DO NOTHING preserves the row
-- across migration re-runs + supabase db reset cycles. The setval call at
-- the end is a no-op under _ctk033_test max=13 per .claude/open-items.md
-- L25 accept-the-gap pattern; sequence stays at 13 until the explicit-id
-- block catches up.
--
-- seed.sql parity note: supabase/seed.sql carries Phase 1 vendors 1-4 only
-- per CTK-028 D3 sub-option (a) ("Phase 2+ vendors deferred to per-vendor
-- tickets"); this migration is the canonical add-path for Vivid Aquariums.
-- Dev-side `supabase db reset` runs migrations BEFORE seed.sql, so the
-- Vivid row lands from this migration; seed.sql's ON CONFLICT preserves it
-- on re-application.

INSERT INTO vendors (id, slug, display_name, base_url, platform, scrape_method, cadence_label, image_strategy, active)
VALUES
  (8, 'vivid-aquariums', 'Vivid Aquariums', 'https://vividaquariums.com', 'shopify', 'products_json', 'hourly', 'mirror', true)
ON CONFLICT (slug) DO NOTHING;

-- Bump the smallserial sequence past the explicit-id INSERT so subsequent
-- vendor INSERTs without an explicit id don't collide on id=8 (or the
-- existing id=13 _ctk033_test row which already holds the sequence). No-op
-- under current sequence state (MAX(id)=13 from _ctk033_test).
SELECT setval(
  pg_get_serial_sequence('vendors', 'id'),
  (SELECT MAX(id) FROM vendors)
);
