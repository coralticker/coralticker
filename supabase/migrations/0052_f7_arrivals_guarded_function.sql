-- CTK-195 D-1 — the shared guarded F7-arrivals source. Re-expresses the CTK-191
-- in-Python honest-count guard (scrapers/tools/content_queries.py:855
-- _guard_arrivals + fetch_arrival_anchors + fetch_trailing_daily_arrivals +
-- _bulk_spike_excluded_cohorts) as SQL, so the DB is the single substrate the
-- Python IG-cover path AND the TS week-feed (lib/queries/listings.ts
-- getRecentArrivals week branch) both route through. A TS-only or Python-only
-- guard recreates the exact two-copies drift this ticket exists to kill.
--
-- Two functions ship here (both CREATE, new names — no DROP, zero blast radius
-- on the live get_listing_lead_event / get_recent_price_drops):
--
--   1. f7_arrivals_dispositioned(window_hours, event_filter) — the 19
--      get_listing_lead_event cols + guard_disposition + bulk_threshold +
--      bulk_median. ONE exclusion pass; every row tagged, nothing dropped.
--   2. get_f7_arrivals_guarded(window_hours, event_filter) — the kept-only
--      consumer: SELECT <19 cols> FROM f7_arrivals_dispositioned WHERE
--      guard_disposition = 'kept'. Returns exactly the get_listing_lead_event
--      shape, a drop-in for the feed RPC (rpcRowToArrival unchanged) and the
--      Python count call-sites.
--
-- ─── Guard semantics (CTK-191 ratified shape — reproduce 788, do NOT improve) ───
--
-- The just-listed arm is the ONLY guarded arm; every other event (back-in-stock,
-- price-dropped) passes through guard_disposition='kept' unconditionally — a
-- restock/drop is inherently cross-scrape, never a cold-start backfill. Two
-- mechanisms run over the just-listed arm in Python order; cold-start precedence
-- means a row removed by mechanism 1 never reaches mechanism 2:
--
--   Mechanism 1 — COLD-START (a newly-onboarded vendor's whole catalog registers
--   as just-listed on its first scrape; we never WATCHED those pieces appear). A
--   just-listed row is cold-start when NO successful scrape finished before its
--   first_seen_at. This is the migration 0046:183-190 anchor predicate
--   (prior_run_finished_at) surfaced per-listing — NOT a fork of
--   get_velocity_listings; the SAME predicate. Expressed as NOT EXISTS, which is
--   equivalent to the Python MAX(finished_at) IS NULL anchor.
--
--   Mechanism 2 — BULK RE-INDEX (a vendor WITH prior runs dumps hundreds of
--   first_seen on one calendar-day — a catalog re-index reading as a surge). Over
--   the cold-start survivors only: a (vendor_id, UTC-day) just-listed cohort trips
--   when count(*) > max(80, 4.0 x the vendor's trailing-median daily arrivals).
--   Strict >. Whole cohort excluded (a re-index is all-or-nothing, never sampled).
--
-- ─── Baseline fidelity notes (the four review findings the 788 test can't catch) ───
--
--   * Baseline scans vendor_listings.first_seen_at RAW — the documented superset
--     skew (content_queries.py:774-782). It can include a vendor's own prior
--     backfill/re-index days, inflating its median and RAISING the threshold. The
--     skew is one-directional (under-exclude only) and carried forward verbatim;
--     tightening it would shift 788 and is deferred to a threshold-tuning pass.
--   * Median via percentile_cont(0.5) — matches Python statistics.median (linear
--     interpolation between the two middle values on even n). percentile_disc
--     would pick the lower middle and silently shift the count.
--   * Trailing window CLAMP: greatest(30, ceil(window_hours/24)). At the default
--     168h this is 30; the clamp only matters at non-default windows (a cohort day
--     older than the baseline's reach would be tested against a baseline that
--     doesn't include its era, the one way the guard could UNDER-count). The 788
--     test runs at 168h and cannot exercise this — it is asserted by reading the
--     SQL body (CTK-195 review finding #3).
--   * Baseline subject = RAW first_seen rows; cohort subject = the warm
--     (cold-start-survivor) just-listed lead-event rows. Two different populations
--     by design — the threshold compares warm-cohort size against a raw-daily
--     median.
--
-- ─── Idempotency + apply path ───
--
-- Both functions are CREATE FUNCTION (new names). GRANTs re-asserted to migration
-- 0039's grantee set (service_role, authenticated, anon). Apply via
-- scripts/apply_migration_0052.py (mirror apply_migration_0046.py shape —
-- scrapers.common.db.get_conn per architecture-v1.md decision #65 / CTK-061).
-- LOAD-BEARING SEQUENCE: apply + 788-verify BEFORE the Python swap merges — the
-- content cron calls these; code ahead of the migration races a missing function.

-- ─── 1. f7_arrivals_dispositioned — disposition-tagged base, one exclusion pass ───
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
  bulk_median numeric
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
  -- Mechanism 1 — cold-start anchor per row. just-listed only; every other event
  -- is passthrough (is_cold_start := false). The NOT EXISTS predicate is the
  -- migration 0046:183-190 anchor surfaced per-listing (== MAX(finished_at) IS NULL).
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
      ) AS is_cold_start
    FROM base b
  ),
  -- Mechanism 2 baseline — per-vendor median of per-active-day RAW first_seen_at
  -- counts over the clamped trailing window, current UTC partial day excluded,
  -- active days only (a zero-arrival day yields no row). RAW = vendor_listings,
  -- NOT the lead-event-filtered cohort (the documented superset skew). Median via
  -- percentile_cont(0.5) = statistics.median.
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
  -- Cohort = (vendor_id, UTC-day) over the warm (cold-start-survivor) just-listed
  -- rows. Day bucket via first_seen_at AT TIME ZONE 'UTC' (matches the baseline +
  -- _arrival_day). A cohort trips when count > max(80, 4.0 x median); strict >,
  -- whole cohort. Threshold arithmetic in double precision to be bit-identical to
  -- Python's max(80.0, 4.0 * median).
  cohort AS (
    SELECT
      a.vendor_id,
      (a.first_seen_at AT TIME ZONE 'UTC')::date AS arr_day,
      count(*) AS cohort_count,
      greatest(80.0::double precision, 4.0::double precision * coalesce(b.med, 0.0::double precision)) AS threshold,
      coalesce(b.med, 0.0::double precision) AS med
    FROM anchored a
    LEFT JOIN baseline b ON b.vendor_id = a.vendor_id
    WHERE a.event = 'just-listed'
      AND a.is_cold_start = false
    GROUP BY a.vendor_id, (a.first_seen_at AT TIME ZONE 'UTC')::date, b.med
  ),
  bulk AS (
    SELECT
      c.vendor_id,
      c.arr_day,
      c.threshold,
      c.med
    FROM cohort c
    WHERE c.cohort_count::double precision > c.threshold
  )
  SELECT
    a.id, a.vendor_id, a.raw_title, a.current_price, a.compare_at_price, a.in_stock,
    a.image_url, a.product_url, a.first_seen_at, a.named_coral_id, a.match_confidence,
    a.event, a.event_at, a.prior_price, a.vendor_slug, a.vendor_display_name,
    a.named_coral_canonical_name, a.named_coral_slug, a.named_coral_origin_vendor,
    CASE
      WHEN a.event <> 'just-listed' THEN 'kept'        -- restock/drop passthrough
      WHEN a.is_cold_start         THEN 'cold_start'   -- mechanism 1 (precedence)
      WHEN bk.vendor_id IS NOT NULL THEN 'bulk_relist' -- mechanism 2 (survivors only)
      ELSE 'kept'
    END AS guard_disposition,
    CASE WHEN a.event = 'just-listed' AND a.is_cold_start = false AND bk.vendor_id IS NOT NULL
         THEN bk.threshold::numeric END AS bulk_threshold,
    CASE WHEN a.event = 'just-listed' AND a.is_cold_start = false AND bk.vendor_id IS NOT NULL
         THEN bk.med::numeric END AS bulk_median
  FROM anchored a
  LEFT JOIN bulk bk
    ON bk.vendor_id = a.vendor_id
   AND bk.arr_day = (a.first_seen_at AT TIME ZONE 'UTC')::date
  ORDER BY a.event_at DESC;
$$;

GRANT EXECUTE ON FUNCTION f7_arrivals_dispositioned(int, text[]) TO service_role, authenticated, anon;


-- ─── 2. get_f7_arrivals_guarded — kept-only consumer, drop-in feed/count shape ───
-- Projects exactly the 19 get_listing_lead_event cols (no disposition cols) so it
-- substitutes for get_listing_lead_event inside orderedEventRows (TS feed) and the
-- Python count call-sites with zero row-shape change. ORDER BY event_at DESC mirrors
-- get_listing_lead_event's contract (the TS wrapper re-sorts, but the parity keeps
-- standalone callers deterministic on the lead axis).
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
