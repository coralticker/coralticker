-- CTK-090 Session 5 — extend `scraper_runs.error_class` CHECK constraint to
-- accept 'config' per CTK-090 Session 4 finding #13 cascade + Q-Backend-6
-- disposition (results.md Session 7 Outstanding Q-Backend-6 2026-05-27).
--
-- CTK-090 Session 4 commit 1c1da73 landed scrapers/common/errors.py +
-- ConfigError + scrapers/common/run.py catch path that writes
-- error_class='config' for empty-category_paths / future user-side YAML or
-- vendors-row config mistakes. The existing CHECK on scraper_runs
-- (`scraper_runs_error_class_check`, defined at 0001_init.sql time with the
-- enum `'http_429','http_5xx','network','html_schema_change','block',
-- 'parse','timeout','other'`) does NOT include 'config' — without this
-- migration, the first production ConfigError catch would explode the
-- orchestrator's `db.finish_scraper_run` call on constraint violation
-- (silent until someone hand-edits a YAML to an empty category_paths, but
-- a latent production failure mode).
--
-- Constraint name `scraper_runs_error_class_check` introspected via
-- pg_constraint pre-write (0014's verify-before-blind-DROP precedent);
-- name follows the PG default <table>_<column>_check convention from
-- 0001_init.sql's inline column-level CHECK declaration.
--
-- Single transaction, DROP+ADD atomic per 0014's autocommit-explicit-wrap
-- canon. scrapers.common.db.get_conn opens the connection with
-- autocommit=True (db.py:61), so without an explicit BEGIN/COMMIT each
-- ALTER commits independently — between the DROP and the ADD there'd be
-- a constraint-absent window where a concurrent INSERT could write
-- `error_class='something_else'` and bypass the whitelist. BEGIN/COMMIT
-- wraps both ALTERs into one transaction; PG's table-level lock on the
-- second ALTER waits for the first to release, so DROP and ADD land
-- atomically from any concurrent reader/writer's perspective.
--
-- Idempotent re-application via `DROP CONSTRAINT IF EXISTS` — re-run after
-- the first apply is a clean no-op.
--
-- Apply path is the architecture-v1.md decision register row #65 canonical
-- — single-file cursor.execute() via scrapers.common.db.get_conn against
-- NEON_DATABASE_URL. Same path as 0014_extend_vendors_platform_bigcommerce
-- .sql + 0015_add_aquasd_vendor.sql.
--
-- Architecture-v1.md §2.4 error_class enum doc-update is a
-- /lead-architect-side follow-up per CTK-090 Session 5 wrap; engineer-side
-- this migration locks the data-plane shape, not the architecture text.

BEGIN;

ALTER TABLE scraper_runs DROP CONSTRAINT IF EXISTS scraper_runs_error_class_check;
ALTER TABLE scraper_runs ADD CONSTRAINT scraper_runs_error_class_check
  CHECK (error_class IN (
    'http_429','http_5xx','network','html_schema_change',
    'block','parse','timeout','other','config'
  ));

COMMIT;
