-- CTK-198 item #4 — exclude single-timestamp bulk-insert cohorts from the
-- get_aggregate_activity headline count. Stacks on CTK-197's migration 0055.
--
-- INV-08 (authored at CTK-198 close): every newness surface that derives a count
-- from vendor_listings reads bulk_cluster / the guarded source. get_aggregate_activity
-- is the "{N} drops across {M} shops" IG headline — built but UNWIRED today (no live
-- caller; _BUILDERS = f7/f8/f9), so this is a latent fix: it changes no live surface,
-- but the count must be honest BEFORE the headline is ever wired (CTK-192 wave-2).
--
-- ─── What this adds (on top of 0055) ───
--
-- 0055 added the equipment denylist to get_aggregate_activity as a 1:1 join-back to
-- vendor_listings (get_listing_lead_event does not project category). This adds the
-- second predicate — vl.bulk_cluster = false — to the SAME join-back WHERE, alongside
-- the equipment gate. bulk_cluster is the persisted single-timestamp cohort flag from
-- CTK-198's primitive (migration 0056: same-(vendor_id, first_seen_at) cohort size >= 50,
-- write-time in diff.py + nightly reconcile). It is a pure function of immutable
-- (vendor_id, first_seen_at), so it persists cleanly — unlike the median-relative
-- cold_start/bulk_relist read-side guard, which it does NOT subsume.
--
-- Magnitude (live 2026-06-25): get_aggregate_activity(168) = ~3634 events drops to
-- ~350 once the predicate lands — the ~90% bulk-dump inflation this guards. The
-- equipment gate alone removes only ~1; bulk_cluster is the load-bearing predicate.
--
-- ─── Idempotency + apply path ───
--
-- CREATE OR REPLACE FUNCTION — no signature / return-type change (unlike 0046's
-- 14->15-col velocity change, which needed DROP), so re-runnable to the same end
-- state. Body is reproduced VERBATIM from migration 0055 with only the
-- `AND vl.bulk_cluster = false` predicate added. Apply via
-- scripts/apply_migration_0058.py (mirrors apply_migration_0055.py:
-- scrapers.common.db.get_conn against NEON_DATABASE_URL per architecture-v1.md
-- decision #65). GRANT EXECUTE re-asserted post-CREATE, same grantee set.
--
-- Authored on the merged 0055 body (origin/main 7839a12) — branching off any
-- pre-0055 commit would re-CREATE OR REPLACE the pre-denylist body and silently
-- drop the equipment gate. The two predicates ride the one join-back together.


-- ─── get_aggregate_activity — equipment denylist (0055) + bulk_cluster guard (0058) ───
--
-- Counts ALL lead-events (matched + unmatched) over a window. The 1:1 join-back to
-- vendor_listings (one lead-event row per listing) carries both gates: COUNT(*) and
-- COUNT(DISTINCT vendor_id) stay the true fleet counts minus equipment minus
-- single-timestamp bulk-dump cohorts.
CREATE OR REPLACE FUNCTION get_aggregate_activity(p_window_hours int DEFAULT 24)
RETURNS TABLE (
  event_count bigint,
  vendor_count bigint,
  window_hours int
)
LANGUAGE sql
STABLE
AS $$
  SELECT
    COUNT(*)::bigint                     AS event_count,
    COUNT(DISTINCT le.vendor_id)::bigint AS vendor_count,
    p_window_hours                       AS window_hours
  FROM get_listing_lead_event(NULL, p_window_hours, NULL, NULL) le
  JOIN vendor_listings vl ON vl.id = le.id
  WHERE vl.category IS DISTINCT FROM 'equipment'   -- INV-07 (CTK-197)
    AND vl.bulk_cluster = false;                   -- INV-08 (CTK-198 item #4)
$$;

GRANT EXECUTE ON FUNCTION get_aggregate_activity(int) TO service_role, authenticated, anon;
