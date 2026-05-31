-- CTK-094 §8.1 — `scraper_runs.per_category_counts` JSONB + `pages_fetched` int.
--
-- DB-visible per-category cohort signal that absorbs the parser-side WARN
-- emitted at scrapers/common/parse_bigcommerce.py L143 (`expected_min_per_category`
-- per-category floor) and gives the operator a persistent signal — the
-- transient WARN log lands in CI stdout and disappears after a few cron
-- cycles. Per CTK-094 D-3 (Q-3 path a + bundle column ratified 2026-05-31),
-- this column is the DB-visible signal that feeds the sibling CTK-097
-- operator Slack alerting (digest + threshold ping); CTK-097 plan-draft
-- activates once this column exists.
--
-- Today's only writer is the BigCommerce-Stencil parser path on AquaSD
-- (vendor_id=7, category_cohort_signal:true in aquasd.yaml). POTO writes
-- {} (single /products.json endpoint, no category surface). Tidal Gardens
-- writes {} (enumerated genus subpaths are coverage-filter, not partial-
-- cohort surface). All 8 stable-catalog vendors write {} (no
-- category_cohort_signal in YAML). Default '{}'::jsonb covers the empty
-- case without per-call branching at the persist site.
--
-- Forward-safe additive: NOT NULL with DEFAULT '{}'::jsonb. PostgreSQL
-- skips the row rewrite for ADD COLUMN ... DEFAULT <constant> on PG11+
-- (metadata-only ALTER, no lock escalation against active scrapers per the
-- same posture as CTK-038 migration 0006). Existing rows materialize the
-- default lazily on next UPDATE (or pg's column-default fast-path on
-- SELECT) — no backfill needed.
--
-- Query shape future-Jon greps:
--   SELECT id, started_at, per_category_counts
--   FROM scraper_runs
--   WHERE vendor_id = 7
--     AND per_category_counts != '{}'::jsonb
--   ORDER BY started_at DESC LIMIT 14;
-- Spotting an N->0 transition on any path is the load-bearing CTK-097
-- operator signal; this column persists the per-scrape numbers so the
-- comparison is N-day-window cheap.
--
-- `pages_fetched` (sibling additive in the same migration). §4.2 completeness
-- signal source-of-truth — the per-vendor 7d-median computed by
-- db.get_7d_median_pages_fetched reads this column. NULLABLE because pre-CTK-094
-- rows do not carry the value (rollout window stays clean — the median query
-- filters IS NOT NULL); steady-state CTK-094-onward rows write a non-null int
-- from every successful scrape regardless of platform. Bundled into the same
-- migration as per_category_counts since both columns are CTK-094 surface and
-- both extend scraper_runs in metadata-only fast-path additive shape.
--
-- Idempotent per CTK-028/032/033/034 migration convention: `ADD COLUMN
-- IF NOT EXISTS` no-ops on re-run.

ALTER TABLE scraper_runs
  ADD COLUMN IF NOT EXISTS per_category_counts JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE scraper_runs
  ADD COLUMN IF NOT EXISTS pages_fetched INTEGER;

COMMENT ON COLUMN scraper_runs.per_category_counts IS
  'CTK-094 per-category cohort signal. JSONB map {category_path: cards_seen} for vendors with category_cohort_signal:true in YAML (AquaSD only at v1; POTO no-op, TG no-op, 8 stable-catalog vendors no-op). Feeds sibling CTK-097 operator Slack alerting (digest + threshold ping). Default ''{}''::jsonb on non-signaling vendors. NOTE per /code-review F7+F13: counts are PRE-overlap-dedup raw card counts, not post-dedup unique listings — categories that share products (AquaSD /softies/ and /zoanthids/ share ~57 cards) sum to more than the deduped items list that lands in vendor_listings. CTK-097 reader MUST treat values as per-path raw-card observability, not unique-product-per-category. A 120-card path dropping to 80 may reflect a 60-card overlap product re-tagged to its sibling path, not 40 actual sell-outs.';

COMMENT ON COLUMN scraper_runs.pages_fetched IS
  'CTK-094 §4.2 completeness signal source-of-truth. Integer count of pages the parser fetched across the run (Shopify /products.json pagination + BC Stencil category_paths cross-product + Magento ?p=N). NULL on pre-CTK-094 rows. Read by db.get_7d_median_pages_fetched to baseline the per-vendor under-scrape WARN.';
