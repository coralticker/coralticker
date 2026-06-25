-- CTK-195 close cleanup — readability + provenance tightening on the CTK-195 D-1
-- guard functions (migration 0052). No behaviour change: byte-for-byte the same
-- disposition outcome + counts; this is a refactor + one new diagnostic column.
--
-- 0052 is applied to Neon, so per apply-immutability discipline this is a NEW
-- migration, not an in-place edit of 0052. Two folds from the /code-review pass:
--
--   Fold #2 (collapse the triple-spelled bulk predicate) — 0052 spelled the bulk
--     condition (event='just-listed' AND NOT is_cold_start AND a matched bulk
--     cohort) THREE times across the guard_disposition / bulk_threshold /
--     bulk_median CASE arms. Compute it ONCE as an is_bulk boolean in a `tagged`
--     CTE; all three output columns branch on it. One source of truth for "this
--     row is a bulk-relist drop."
--
--   Fold #3 (project arr_day) — the function buckets the bulk cohort on
--     (first_seen_at AT TIME ZONE 'UTC')::date. The Python wrapper
--     (_guard_arrivals) re-derived that day via _arrival_day(row) to key its
--     drop-log cohort map — a SECOND computation of the same day that could drift
--     (first_seen_at-vs-event_at fallback, string-parse path). Project the day the
--     function actually grouped on as arr_day so the wrapper reads it straight,
--     killing the second source of truth.
--
-- arr_day is computed ONCE in the `anchored` CTE and reused by the cohort grouping,
-- the bulk join, AND the output column, so the cohort key and the projected day are
-- definitionally identical.
--
-- Return-shape changes (arr_day added), so DROP + CREATE, not CREATE OR REPLACE.
-- get_f7_arrivals_guarded calls f7_arrivals_dispositioned by name + selects the same
-- 19 cols, so its body is unchanged — but it is dropped + recreated first/last to
-- keep the apply order dependency-safe (drop the caller before the callee, recreate
-- the callee before the caller). GRANTs re-asserted to the 0039 grantee set.
--
-- NOTE (NOT folded here — CTK-195 finding #1, pending Jon's ruling): the TS week
-- feed (orderedEventRows) excludes category='equipment'; this guard does not, so the
-- guarded population is a superset of the feed's by the equipment arrivals. Whether
-- to push an equipment filter into this shared source (shifts the ratified count) or
-- soften the listings.ts reconciliation comment is held for that decision — this
-- migration deliberately does NOT add a category filter.
--
-- Apply via scripts/apply_migration_0053.py (mirror apply_migration_0052.py).

DROP FUNCTION IF EXISTS get_f7_arrivals_guarded(int, text[]);
DROP FUNCTION IF EXISTS f7_arrivals_dispositioned(int, text[]);


-- ─── f7_arrivals_dispositioned — disposition-tagged base (+ arr_day) ───
CREATE FUNCTION f7_arrivals_dispositioned(
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
    -- make the guard count a sample. event_filter passes through verbatim; the
    -- function already applies it as a post-rank lead-event selector.
    SELECT * FROM get_listing_lead_event(NULL, window_hours, event_filter, NULL)
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
  -- Fold #2: compute is_bulk ONCE (a warm just-listed row matched to a tripped
  -- cohort), so the disposition CASE + bulk_threshold + bulk_median all branch on the
  -- one boolean instead of re-spelling the predicate three times.
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


-- ─── get_f7_arrivals_guarded — kept-only consumer, 19-col drop-in (body unchanged) ───
CREATE FUNCTION get_f7_arrivals_guarded(
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
  named_coral_origin_vendor text
)
LANGUAGE sql
STABLE
AS $$
  SELECT
    id, vendor_id, raw_title, current_price, compare_at_price, in_stock,
    image_url, product_url, first_seen_at, named_coral_id, match_confidence,
    event, event_at, prior_price, vendor_slug, vendor_display_name,
    named_coral_canonical_name, named_coral_slug, named_coral_origin_vendor
  FROM f7_arrivals_dispositioned(window_hours, event_filter)
  WHERE guard_disposition = 'kept'
  ORDER BY event_at DESC;
$$;

GRANT EXECUTE ON FUNCTION get_f7_arrivals_guarded(int, text[]) TO service_role, authenticated, anon;
