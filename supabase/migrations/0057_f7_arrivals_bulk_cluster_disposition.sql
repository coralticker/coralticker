-- CTK-198 (Tier 1B) — add `bulk_cluster` as the 4th disposition in
-- f7_arrivals_dispositioned, so the F7 IG cover + the web /new?window=week feed
-- (both route this shared source via CTK-195) exclude single-timestamp batch
-- dumps the median-relative CTK-191 guard misses.
--
-- ─── The one change ───
--
-- The function READS the persisted vendor_listings.bulk_cluster column (migration
-- 0056) — it does NOT re-derive the cohort-size threshold (that lives once in
-- scrapers/common/bulk_cluster.py BULK_CLUSTER_MIN, written by the diff.py hook +
-- the nightly audit). The base CTE already JOINs vendor_listings (for the CTK-195
-- equipment denylist), so projecting vl.bulk_cluster adds NO new join. A single new
-- CASE branch — 'bulk_cluster', precedence LAST (after bulk_relist, before
-- ELSE 'kept') — tags surviving just-listed dump rows.
--
-- Restocks/drops pass through 'kept' unchanged (the first CASE arm fires on
-- event <> 'just-listed' before bulk_cluster is consulted), mirroring how
-- cold_start / bulk_relist only ever tag just-listed rows. A row both cold_start
-- and bulk_cluster tags cold_start (precedence); both bulk_relist and bulk_cluster
-- tags bulk_relist — the label is provenance, and all three drop the row from
-- 'kept' identically.
--
-- ─── Why this reaches both consumers for free ───
--
-- get_f7_arrivals_guarded is UNCHANGED — its WHERE guard_disposition = 'kept'
-- already drops every non-kept disposition, so the new 'bulk_cluster' tag is
-- excluded for free. The Python cover path (_guard_arrivals) reads
-- f7_arrivals_dispositioned directly and partitions on guard_disposition, so it
-- too drops 'bulk_cluster' from `kept` with no Python change (the optional operator
-- log line for bulk_cluster_dropped is a separate, additive diagnostic).
--
-- ─── DDL shape ───
--
-- RETURNS TABLE shape is UNCHANGED (the disposition is already a text column; the
-- new tag is a new value, not a new column), so CREATE OR REPLACE is correct — no
-- DROP, no consumer-dangling window. Body is reproduced verbatim from migration
-- 0054 with only (a) `vl.bulk_cluster` added to the base CTE projection and (b) the
-- one new CASE branch. 0054 is left intact per apply-immutability; this is a new
-- migration. GRANT re-asserted to the 0054 grantee set. Apply via
-- scripts/apply_migration_0057.py. Applies AFTER 0056 (the column must exist).

CREATE OR REPLACE FUNCTION f7_arrivals_dispositioned(
  window_hours int DEFAULT 168,
  event_filter text[] DEFAULT NULL
)
RETURNS TABLE (
  id bigint,
  vendor_id smallint,
  raw_title text,
  current_price numeric,
  compare_at_price numeric,
  in_stock boolean,
  image_url text,
  product_url text,
  first_seen_at timestamptz,
  named_coral_id integer,
  match_confidence text,
  event text,
  event_at timestamptz,
  prior_price numeric,
  vendor_slug text,
  vendor_display_name text,
  named_coral_canonical_name text,
  named_coral_slug text,
  named_coral_origin_vendor text,
  guard_disposition text,
  bulk_threshold numeric,
  bulk_median numeric,
  arr_day date
)
LANGUAGE sql
STABLE
AS $$
  WITH base AS (
    -- Inner source MUST be uncapped (row_limit := NULL) — a truncated 100 would
    -- make the guard count a sample. event_filter passes through verbatim (the
    -- function applies it as a post-rank lead-event selector). CTK-195 finding #1:
    -- JOIN vendor_listings to drop equipment via the CTK-186 step-2 predicate, so the
    -- guarded population is coral-only — the same population the web feed renders.
    -- CTK-198: project vl.bulk_cluster off the SAME join (no new join) — the
    -- persisted single-timestamp-dump flag, read not re-derived.
    SELECT le.*, vl.bulk_cluster
    FROM get_listing_lead_event(NULL, window_hours, event_filter, NULL) le
    JOIN vendor_listings vl ON vl.id = le.id
    WHERE vl.category IS DISTINCT FROM 'equipment'   -- denylist; NULL-safe (keeps NULL-category corals)
  ),
  -- Mechanism 1 — cold-start anchor per row + the UTC cohort day, both computed once.
  -- just-listed only is cold-start-eligible; every other event is passthrough. The
  -- NOT EXISTS predicate is the migration 0046:183-190 anchor surfaced per-listing
  -- (== MAX(finished_at) IS NULL). arr_day is the cohort key the bulk grouping, the
  -- bulk join, and the output column all share — one computation, no drift.
  anchored AS (
    SELECT
      b.*,
      (
        b.event = 'just-listed'
        AND NOT EXISTS (
          SELECT 1
          FROM scraper_runs sr
          WHERE sr.vendor_id = b.vendor_id
            AND sr.status = 'success'
            AND sr.finished_at IS NOT NULL
            AND sr.finished_at < b.first_seen_at
        )
      ) AS is_cold_start,
      (b.first_seen_at AT TIME ZONE 'UTC')::date AS arr_day
    FROM base b
  ),
  -- Mechanism 2 baseline — per-vendor median of per-active-day RAW first_seen_at
  -- counts over the clamped trailing window, current UTC partial day excluded,
  -- active days only. RAW = vendor_listings, NOT the lead-event-filtered cohort (the
  -- documented superset skew). Median via percentile_cont(0.5) = statistics.median.
  daily AS (
    SELECT
      vl.vendor_id,
      count(*) AS cnt
    FROM vendor_listings vl
    WHERE vl.first_seen_at >= now() - make_interval(days => greatest(30, ceil(window_hours::numeric / 24)::int))
      AND (vl.first_seen_at AT TIME ZONE 'UTC')::date < (now() AT TIME ZONE 'UTC')::date
    GROUP BY vl.vendor_id, (vl.first_seen_at AT TIME ZONE 'UTC')::date
  ),
  baseline AS (
    SELECT
      d.vendor_id,
      percentile_cont(0.5) WITHIN GROUP (ORDER BY d.cnt) AS med   -- double precision; == statistics.median
    FROM daily d
    GROUP BY d.vendor_id
  ),
  -- Cohort = (vendor_id, arr_day) over the warm (cold-start-survivor) just-listed
  -- rows. Trips when count > max(80, 4.0 x median); strict >, whole cohort. Threshold
  -- arithmetic in double precision to be bit-identical to Python max(80.0, 4.0*median).
  cohort AS (
    SELECT
      a.vendor_id,
      a.arr_day,
      count(*) AS cohort_count,
      greatest(80.0::double precision, 4.0::double precision * coalesce(b.med, 0.0::double precision)) AS threshold,
      coalesce(b.med, 0.0::double precision) AS med
    FROM anchored a
    LEFT JOIN baseline b ON b.vendor_id = a.vendor_id
    WHERE a.event = 'just-listed'
      AND a.is_cold_start = false
    GROUP BY a.vendor_id, a.arr_day, b.med
  ),
  bulk AS (
    SELECT c.vendor_id, c.arr_day, c.threshold, c.med
    FROM cohort c
    WHERE c.cohort_count::double precision > c.threshold
  ),
  -- is_bulk computed ONCE (a warm just-listed row matched to a tripped cohort), so the
  -- disposition CASE + bulk_threshold + bulk_median all branch on the one boolean.
  tagged AS (
    SELECT
      a.*,
      (a.event = 'just-listed' AND a.is_cold_start = false AND bk.vendor_id IS NOT NULL) AS is_bulk,
      bk.threshold AS bulk_threshold_d,
      bk.med       AS bulk_median_d
    FROM anchored a
    LEFT JOIN bulk bk
      ON bk.vendor_id = a.vendor_id
     AND bk.arr_day = a.arr_day
  )
  SELECT
    t.id, t.vendor_id, t.raw_title, t.current_price, t.compare_at_price, t.in_stock,
    t.image_url, t.product_url, t.first_seen_at, t.named_coral_id, t.match_confidence,
    t.event, t.event_at, t.prior_price, t.vendor_slug, t.vendor_display_name,
    t.named_coral_canonical_name, t.named_coral_slug, t.named_coral_origin_vendor,
    CASE
      WHEN t.event <> 'just-listed' THEN 'kept'         -- restock/drop passthrough
      WHEN t.is_cold_start          THEN 'cold_start'   -- mechanism 1 (precedence)
      WHEN t.is_bulk                THEN 'bulk_relist'   -- mechanism 2 (survivors only)
      WHEN t.bulk_cluster           THEN 'bulk_cluster'  -- CTK-198 (persisted; precedence last)
      ELSE 'kept'
    END AS guard_disposition,
    CASE WHEN t.is_bulk THEN t.bulk_threshold_d::numeric END AS bulk_threshold,
    CASE WHEN t.is_bulk THEN t.bulk_median_d::numeric    END AS bulk_median,
    t.arr_day
  FROM tagged t
  ORDER BY t.event_at DESC;
$$;

GRANT EXECUTE ON FUNCTION f7_arrivals_dispositioned(int, text[]) TO service_role, authenticated, anon;
