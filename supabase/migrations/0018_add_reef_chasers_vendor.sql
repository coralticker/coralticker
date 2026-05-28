-- CTK-086 Session 3 — Reef Chasers vendors row (Phase 2 scraper #9).
--
-- Closes the data-side prerequisite for the Reef Chasers scraper landing in
-- the same CTK Session: scrapers/common/run.py:db.fetch_vendor() reads this
-- row at stage 1 (Config) of the arch §2.1 lifecycle, then merges with
-- scrapers/vendors/reef-chasers.yaml per arch §2.3 (DB row wins on
-- conflict). Without this row, the scraper fails fast at stage 1 — the
-- right shape; loud-failure-not-silent-skip.
--
-- vendor_id=9 disposition per CTK-086 plan §Scope item 4 + sequential
-- precedent (Battlecorals id=5, Unique Corals id=6, AquaSD id=7, Vivid
-- id=8). FK joins on vendor_listings.vendor_id = vendors.id are safe;
-- literal hardcodes of vendor_id=9 in matcher / notifier / analytics
-- modules fire the open-items.md L25 vendor-ID stability watch trigger
-- and graduate to INV-03 if a second consumer pattern lands.
--
-- Vendor-ID gap acknowledgement (CTK-085 Session 2 Q-3 disposition
-- inherited): a test row from a prior CTK holds the vendors.id smallserial
-- sequence ABOVE this explicit-id INSERT, so the trailing setval is a
-- no-op (explicit id=9 < current sequence max → setval(MAX(id)) leaves the
-- sequence unchanged). Reef Chasers explicit-id=9 INSERT continues the
-- accept-the-gap path; id range remains contiguous in the 5-9 explicit
-- Phase 2 block.
--
-- Sequence-holder note (CTK-086 Session 3 reconciliation): prior vendor-add
-- migrations (0010/0011/0015/0017) + open-items.md L25 describe the
-- sequence holder as `_ctk033_test` at id=13. Per the CTK-086 Session 2
-- verify-pass DB observation the holder is actually `_ctk029_test` at
-- id=14. The no-op mechanism is identical either way (id=9 is below both
-- 13 and 14). The prior-migration comment drift (13 vs. 14 / _ctk033_test
-- vs. _ctk029_test) is a doc-only discrepancy flagged for /lead-backend
-- minor-cleanup at close; it does NOT affect this migration's correctness.
--
-- vendors-row columns (per supabase/migrations/0001_init.sql:40-53 schema):
--   - id = 9            smallserial primary key; explicit literal here for
--                       open-items.md L25 vendor-ID stability watch.
--   - slug = 'reef-chasers'        matches scrapers/vendors/reef-chasers.yaml
--                                   slug + .github/workflows/reef-chasers.yml
--                                   workflow name (run.py CLI arg).
--   - display_name = 'Reef Chasers'  TN vendor, 10k-gal facility, fish +
--                                     invert + coral multi-category catalog
--                                     per .claude/research/phase-1.5-vendor-
--                                     scan.md close summary; QCC swap
--                                     candidate selected 2026-04-24.
--   - base_url = 'https://reefchasers.com'  canonical public domain
--                                            (reef-chasers.com is NXDOMAIN;
--                                            hyphenated form is the
--                                            .myshopify.com shop slug only).
--   - platform = 'shopify'         five-signal pre-flight 2026-05-28 (cite-
--                                   back in scrapers/vendors/reef-chasers.yaml)
--   - scrape_method = 'products_json'  canonical Shopify endpoint shape
--   - cadence_label = 'hourly'     arch §2.7 decision #15 + CTK-086 plan
--                                   §Decisions Q-3 cadence lock (41 * * * *
--                                   UTC, off-minute per open-items.md L53 +
--                                   L60 discipline)
--   - image_strategy = 'mirror'    default per arch §1.3 + CTK-019 #52;
--                                   runtime-flippable to 'hotlink' on vendor
--                                   pushback via UPDATE (no code commit)
--   - active = true                workflow_dispatch fires immediately; first
--                                   scheduled cron firing observed at next
--                                   :41 boundary (~60-min wait max under
--                                   hourly cadence)
--
-- Idempotent re-application: ON CONFLICT (slug) DO NOTHING preserves the row
-- across migration re-runs + supabase db reset cycles.
--
-- seed.sql parity note: supabase/seed.sql carries Phase 1 vendors 1-4 only
-- per CTK-028 D3 sub-option (a) ("Phase 2+ vendors deferred to per-vendor
-- tickets"); this migration is the canonical add-path for Reef Chasers.
-- Dev-side `supabase db reset` runs migrations BEFORE seed.sql, so the
-- Reef Chasers row lands from this migration; seed.sql's ON CONFLICT
-- preserves it on re-application.

INSERT INTO vendors (id, slug, display_name, base_url, platform, scrape_method, cadence_label, image_strategy, active)
VALUES
  (9, 'reef-chasers', 'Reef Chasers', 'https://reefchasers.com', 'shopify', 'products_json', 'hourly', 'mirror', true)
ON CONFLICT (slug) DO NOTHING;

-- Bump the smallserial sequence past the explicit-id INSERT so subsequent
-- vendor INSERTs without an explicit id don't collide on id=9. No-op under
-- current sequence state (a prior-CTK test row holds the sequence max above
-- id=9 — id=14 per CTK-086 Session 2 verify-pass observation).
SELECT setval(
  pg_get_serial_sequence('vendors', 'id'),
  (SELECT MAX(id) FROM vendors)
);
