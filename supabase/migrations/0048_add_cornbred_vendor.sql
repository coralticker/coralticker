-- CTK-142 Session 2 — Cornbred Corals vendors row (Phase 2 vendor wave,
-- demand-mine candidate #1; scraper #12).
--
-- Closes the data-side prerequisite for the Cornbred scraper landing in the
-- same CTK: scrapers/common/run.py db.fetch_vendor() reads this row at stage 1
-- (Config) of the arch §2.1 lifecycle, then merges with
-- scrapers/vendors/cornbred.yaml per arch §2.3 (DB row wins on conflict).
-- Without this row the scraper fails fast at stage 1 — the right shape;
-- loud-failure-not-silent-skip.
--
-- vendor_id=12 disposition: continues the explicit-id Phase 2 block (Battlecorals
-- 5, Unique Corals 6, AquaSD 7, Vivid 8, Reef Chasers 9, POTO 10, Tidal Gardens
-- 11). id=12 is the next contiguous real-vendor id — verified free against the
-- live table 2026-06-20 (real vendors 1-11 contiguous; id=12 is the gap before
-- the _ctkNNN_test rows at 13+). FK joins on vendor_listings.vendor_id =
-- vendors.id are safe; literal hardcodes of vendor_id=12 in matcher / notifier /
-- analytics modules fire the open-items.md L25 vendor-ID stability watch trigger
-- and graduate to INV-03 if a second consumer pattern lands.
--
-- Sequence-holder note: the vendors.id smallserial sequence is held ABOVE this
-- explicit-id INSERT by a prior-CTK test row (live observation 2026-06-20:
-- MAX(id)=32, _ctk042_test). So the trailing setval(MAX(id)) is a no-op
-- (explicit id=12 < current sequence max → setval leaves the sequence
-- unchanged). Cornbred explicit-id=12 INSERT fills the 11→13 gap and keeps the
-- real-vendor id range contiguous in the 1-12 block.
--
-- Slug canon (CTK-044 / CTK-095): public URLs kebab; DB / YAML / R2 paths
-- snake. Cornbred is a single-token vendor, so slug 'cornbred' is unambiguous
-- (no kebab→snake normalization needed, unlike the CTK-095 0022 Phase-2 fix
-- for reef_chasers / tidal_gardens / unique_corals / vivid_aquariums). The
-- slug matches scrapers/vendors/cornbred.yaml `slug:` + the .github/workflows/
-- cornbred-corals.yml `python -m scrapers.common.run cornbred` CLI arg in
-- lock-step.
--
-- vendors-row columns (per supabase/migrations/0001_init.sql schema):
--   - id = 12               smallserial primary key; explicit literal here for
--                           open-items.md L25 vendor-ID stability watch.
--   - slug = 'cornbred'     matches cornbred.yaml slug + cornbred-corals.yml
--                           workflow CLI arg (run.py <slug>).
--   - display_name = 'Cornbred Corals'  named-coral originator house (Utter
--                                        Chaos Paly, El Diablo Chalice, Mortal
--                                        Kombat Paly canonical lineages); top
--                                        demand-mine target (CB 67 mentions /
--                                        5 vendors, 2026-06-11 acronym-mine).
--   - base_url = 'https://cornbredcorals.com'  canonical public domain
--                                               (five-signal pre-flight
--                                               2026-06-20).
--   - platform = 'shopify'         five-signal pre-flight 2026-06-20 (cite-back
--                                   in scrapers/vendors/cornbred.yaml).
--   - scrape_method = 'products_json'  canonical Shopify endpoint shape.
--   - cadence_label = 'hourly'     arch §2.7 decision #15 + CTK-142 cadence
--                                   lock (47 * * * * UTC, off-minute per
--                                   open-items.md off-minute discipline).
--   - image_strategy = 'mirror'    default per arch §1.3 + CTK-019 #52;
--                                   runtime-flippable to 'hotlink' on vendor
--                                   pushback via UPDATE (no code commit).
--   - active = true                workflow_dispatch fires immediately; first
--                                   scheduled cron firing observed at the next
--                                   :47 boundary (~60-min wait max under hourly
--                                   cadence).
--
-- Idempotent re-application: ON CONFLICT (slug) DO NOTHING preserves the row
-- across migration re-runs + supabase db reset cycles.
--
-- seed.sql parity note: supabase/seed.sql carries Phase 1 vendors 1-4 only per
-- CTK-028 D3 sub-option (a) ("Phase 2+ vendors deferred to per-vendor
-- tickets"); this migration is the canonical add-path for Cornbred. Dev-side
-- `supabase db reset` runs migrations BEFORE seed.sql, so the Cornbred row
-- lands from this migration; seed.sql's ON CONFLICT preserves it on
-- re-application.

INSERT INTO vendors (id, slug, display_name, base_url, platform, scrape_method, cadence_label, image_strategy, active)
VALUES
  (12, 'cornbred', 'Cornbred Corals', 'https://cornbredcorals.com', 'shopify', 'products_json', 'hourly', 'mirror', true)
ON CONFLICT (slug) DO NOTHING;

-- Bump the smallserial sequence past the explicit-id INSERT so subsequent
-- vendor INSERTs without an explicit id don't collide on id=12. No-op under
-- current sequence state (a prior-CTK test row holds the sequence max above
-- id=12 — MAX(id)=32 per the 2026-06-20 live observation).
SELECT setval(
  pg_get_serial_sequence('vendors', 'id'),
  (SELECT MAX(id) FROM vendors)
);
