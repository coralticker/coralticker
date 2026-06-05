-- 0032_pg_trgm_search_index.sql
--
-- CTK-058 v1 site-nav search (plan D-058-1): trigram GIN on
-- vendor_listings.normalized_title so the /search listings class's per-token
-- `ILIKE '%tok%'` predicates stay indexed as the corpus grows past seq-scan
-- comfort. vendors (11 rows) and the named_corals + aliases dictionary
-- (20 + 41 rows) deliberately get no index — seq scan wins at that scale.
--
-- pg_trgm is already installed on the Neon project (v1.6, verified at
-- Session 1 open alongside the CREATE EXTENSION privilege probe); the
-- IF NOT EXISTS keeps this migration replayable on a fresh database.
--
-- Additive only — no table rewrites, no cron-window state risk
-- (feedback_yaml_state_cron_window_risk does not apply).

BEGIN;

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE INDEX IF NOT EXISTS idx_vl_normalized_title_trgm
  ON vendor_listings USING gin (normalized_title gin_trgm_ops);

COMMIT;
