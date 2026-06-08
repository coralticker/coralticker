-- CTK-137 T-1 — cohort flip-cap stateful convergence: per-run absent-set
-- tracking on scraper_runs.
--
-- Two additive, nullable columns let a settled real catalog shift > the
-- CTK-120 flip cap auto-converge after K consecutive runs observe the SAME
-- cohort-OOS absent-set (self-lock escape), instead of staying tripped
-- indefinitely until an operator one-shot flush:
--
--   cohort_absent_set_hash  sha256 of the sorted product_url set in the run's
--                           cohort-OOS absent-set (run.py _cohort_absent_set_hash).
--                           NULL when no cohort decisions were computed / the
--                           cohort was not evaluated (canary/fetch failure).
--                           The convergence check keys on K-1 prior runs all
--                           carrying the same non-NULL hash; NULL is treated as
--                           "no stable history", so the check never converges
--                           off a NULL.
--   cohort_absent_count     len(cohort_oos_decisions) at gate time. Distinct
--                           from listings_oos, which is 0 on a dropped/tripped
--                           run — this is the would-flip count for observability
--                           and the deferred health-digest cohort section.
--
-- Additive only: both nullable, no NOT NULL on existing rows, no backfill.
-- Pre-CTK-137 rows keep NULL hash and are inert to the convergence logic, so
-- no data migration is needed (D-4).
--
-- NOT a content/completeness proxy: the hash is over the absent-set membership,
-- NOT the Shopify html_hash schema sentinel (which is item-count-invariant and
-- stayed byte-identical through the PE 2026-06-08 delist — the load-bearing
-- input that rules html_hash out as a convergence signal).

-- IF NOT EXISTS so the apply script is idempotent (re-run rebinds nothing).
ALTER TABLE scraper_runs
    ADD COLUMN IF NOT EXISTS cohort_absent_set_hash text,
    ADD COLUMN IF NOT EXISTS cohort_absent_count integer;
