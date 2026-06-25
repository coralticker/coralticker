-- CTK-195 finding #1 — exclude equipment from the shared guarded source so the IG
-- cover (select_f7_arrivals / count_new_arrivals) and the web /new?window=week feed
-- count ONE coral-only population. Jon-decided 2026-06-25 (outcome a), reversing the
-- earlier soften-the-comment lean: CTK-186 step-2 established equipment-exclusion +
-- matching counts as Tier-1B intent ("counts in lockstep" was its close acceptance),
-- so the guard — which didn't exclude equipment — was the inconsistency, not the
-- comment.
--
-- The guard's inner get_listing_lead_event projects no category, so JOIN
-- vendor_listings and apply the EXACT CTK-186 step-2 predicate in the base CTE:
--
--     vl.category IS DISTINCT FROM 'equipment'
--
-- DENYLIST, not allowlist (load-bearing per CTK-186 + CTK-194): IS DISTINCT FROM is
-- NULL-safe, so it keeps the ~1.8k in-stock NULL-category corals (CTK-194 — the
-- category classifier doesn't tag every coral yet). A coral-allowlist
-- (category IN (...)) would wrongly drop every NULL-category coral. Do not use one.
--
-- Placed in the BASE CTE of f7_arrivals_dispositioned (not in get_f7_arrivals_guarded)
-- so BOTH consumers inherit it: the Python cover path reads f7_arrivals_dispositioned
-- directly (via _guard_arrivals), and get_f7_arrivals_guarded selects from it. One
-- predicate, one population — the IG cover count == the web week-feed count
-- STRUCTURALLY now (both exclude equipment), not just empirically.
--
-- Count re-base: this corrects the ratified 788, which OVER-counted equipment
-- arrivals. Equipment arrivals are near-zero today (~38 equipment listings fleet-wide,
-- few of them just-listed/back-in-stock in-window), so the number barely moves — but
-- the exclusion is now structural, not incidental.
--
-- Shape UNCHANGED (a base-CTE filter adds no column), so CREATE OR REPLACE is the
-- correct DDL — not DROP + CREATE (which the directive named for the general
-- shape-change case; there is no return-type change here, and get_f7_arrivals_guarded
-- is unaffected, so REPLACE is both valid and safer — no window where the consumer
-- references a dropped callee). 0053 is left intact per apply-immutability; this is a
-- new migration. GRANT re-asserted to the 0039 grantee set. Apply via
-- scripts/apply_migration_0054.py.

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
    SELECT le.*
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
      WHEN t.event <> 'just-listed' THEN 'kept'        -- restock/drop passthrough
      WHEN t.is_cold_start          THEN 'cold_start'  -- mechanism 1 (precedence)
      WHEN t.is_bulk                THEN 'bulk_relist'  -- mechanism 2 (survivors only)
      ELSE 'kept'
    END AS guard_disposition,
    CASE WHEN t.is_bulk THEN t.bulk_threshold_d::numeric END AS bulk_threshold,
    CASE WHEN t.is_bulk THEN t.bulk_median_d::numeric    END AS bulk_median,
    t.arr_day
  FROM tagged t
  ORDER BY t.event_at DESC;
$$;

GRANT EXECUTE ON FUNCTION f7_arrivals_dispositioned(int, text[]) TO service_role, authenticated, anon;
