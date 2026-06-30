-- CTK-212 follow-up (INV-07 / CTK-197 completion) -- widen the category denylist
-- from {equipment} to {equipment, invert} across all six INV-07 content functions.
--
-- WHY: CTK-212 onboarded Biota, the first vendor stocking invertebrates by design
-- (~15 live rows, category='invert'). INV-07 (CTK-197) excludes equipment from every
-- count / aggregate / feed surface, but the literal was equipment-only, so Biota's
-- inverts leaked into these six functions (and the email digest -- fixed TS-side in
-- the same CTK). This migration brings the SQL surfaces to {equipment, invert} parity.
--
-- FORM: NULL-safe set form -- (vl.category IS NULL OR vl.category <> ALL(ARRAY
-- ['equipment','invert']::text[])). The IS NULL arm is load-bearing: reclassified
-- None-category corals carry category=NULL and MUST stay visible (a bare <> ALL would
-- drop them -- NULL <> ALL -> NULL -> excluded). Matches the TS EXCLUDED_CATEGORIES
-- set form bare /new + the digest use (lib/queries/category-exclusion.ts).
--
-- SHAPE: CREATE OR REPLACE, NO signature change -- each body is the LIVE
-- pg_get_functiondef output with ONLY the single category-predicate line rewritten
-- (generated, not hand-transcribed, so no body drift). Idempotent on re-run.
-- get_listing_lead_event is deliberately NOT touched (no category column; the IG/digest
-- pool filters category Python/TS-side).
--
-- Functions (latest defs): f7_arrivals_dispositioned (0057), get_aggregate_activity
-- (0058), get_velocity_listings (0066), get_cross_vendor_cheapest (0066),
-- get_most_restocked (0066), get_vendor_drop_cadence (0062).
--
-- Verify post-apply: pg_get_functiondef of all six carries 'invert' (committed != applied,
-- feedback_migration_committed_not_applied); + the INV-07 parity test
-- (test_inv07_category_denylist_parity) asserts the canonical {equipment,invert} set.

-- ===== f7_arrivals_dispositioned =====
CREATE OR REPLACE FUNCTION public.f7_arrivals_dispositioned(window_hours integer DEFAULT 168, event_filter text[] DEFAULT NULL::text[])
 RETURNS TABLE(id bigint, vendor_id smallint, raw_title text, current_price numeric, compare_at_price numeric, in_stock boolean, image_url text, product_url text, first_seen_at timestamp with time zone, named_coral_id integer, match_confidence text, event text, event_at timestamp with time zone, prior_price numeric, vendor_slug text, vendor_display_name text, named_coral_canonical_name text, named_coral_slug text, named_coral_origin_vendor text, guard_disposition text, bulk_threshold numeric, bulk_median numeric, arr_day date)
 LANGUAGE sql
 STABLE
AS $function$
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
    JOIN vendors av ON av.id = vl.vendor_id                       -- CTK-213
      AND av.active = true AND av.slug NOT LIKE '!_%' ESCAPE '!'  -- CTK-213 test/inactive-vendor exclusion
    WHERE (vl.category IS NULL OR vl.category <> ALL(ARRAY['equipment','invert']::text[]))  -- INV-07 (CTK-197); CTK-212 + invert -- NULL-safe (keeps NULL-category corals)
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
    JOIN vendors av ON av.id = vl.vendor_id                       -- CTK-213
      AND av.active = true AND av.slug NOT LIKE '!_%' ESCAPE '!'  -- CTK-213 test/inactive-vendor exclusion
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
$function$;


-- ===== get_aggregate_activity =====
CREATE OR REPLACE FUNCTION public.get_aggregate_activity(p_window_hours integer DEFAULT 24)
 RETURNS TABLE(event_count bigint, vendor_count bigint, window_hours integer)
 LANGUAGE sql
 STABLE
AS $function$
  SELECT
    COUNT(*)::bigint                     AS event_count,
    COUNT(DISTINCT le.vendor_id)::bigint AS vendor_count,
    p_window_hours                       AS window_hours
  FROM get_listing_lead_event(NULL, p_window_hours, NULL, NULL) le
  JOIN vendor_listings vl ON vl.id = le.id
  JOIN vendors av ON av.id = vl.vendor_id                         -- CTK-213
    AND av.active = true AND av.slug NOT LIKE '!_%' ESCAPE '!'  -- CTK-213 test/inactive-vendor exclusion
  WHERE (vl.category IS NULL OR vl.category <> ALL(ARRAY['equipment','invert']::text[]))  -- INV-07 (CTK-197); CTK-212 + invert -- NULL-safe (keeps NULL-category corals)
    AND vl.bulk_cluster = false;                   -- INV-08 (CTK-198 item #4)
$function$;


-- ===== get_velocity_listings =====
CREATE OR REPLACE FUNCTION public.get_velocity_listings(p_window_days integer DEFAULT NULL::integer)
 RETURNS TABLE(id bigint, vendor_id smallint, named_coral_id integer, first_seen_at timestamp with time zone, last_in_stock_at timestamp with time zone, first_oos_at timestamp with time zone, prior_run_finished_at timestamp with time zone, raw_title text, image_url text, product_url text, current_price numeric, vendor_slug text, vendor_display_name text, named_coral_canonical_name text, named_coral_slug text)
 LANGUAGE sql
 STABLE
AS $function$
  WITH oos AS (
    -- The piece is gone (still-OOS) and we can name it (the render needs the
    -- coral — vendor identity line; an unnameable coral can't carry the claim).
    -- Auction double-gate (see 0046 header): an auction's OOS is its clock, not
    -- demand, so it cannot carry a velocity (speed-of-sale) claim.
    SELECT
      vl.id, vl.vendor_id, vl.named_coral_id, vl.raw_title, vl.image_url,
      vl.product_url, vl.current_price
    FROM vendor_listings vl
    WHERE vl.in_stock = false
      AND vl.named_coral_id IS NOT NULL
      AND vl.auction_end_time IS NULL            -- INV-05 residual (D-3)
      AND vl.is_auction = false                  -- CTK-042 pseudo-auction gate
      AND (vl.category IS NULL OR vl.category <> ALL(ARRAY['equipment','invert']::text[]))  -- INV-07 (CTK-197); CTK-212 + invert -- NULL-safe (keeps NULL-category corals)
  ),
  obs AS (
    -- First real-time in-stock observation, off append-only price_history
    -- (decision #7). A listing first observed OOS (then restocked) is common, so
    -- first_seen_at is the first in_stock = true row, NOT the first row.
    SELECT
      ph.listing_id,
      MIN(ph.observed_at) FILTER (WHERE ph.in_stock) AS first_seen_at
    FROM price_history ph
    JOIN oos ON oos.id = ph.listing_id
    GROUP BY ph.listing_id
  ),
  firstoos AS (
    -- First OOS TRANSITION = first in_stock = false AFTER the first in-stock
    -- observation (a false that PRECEDES first_seen_at is a prior state, not a
    -- transition out of stock). The INNER JOIN drops listings with no such
    -- transition — nothing to measure. Requires we actually saw it in stock.
    SELECT
      obs.listing_id,
      obs.first_seen_at,
      MIN(ph.observed_at) AS first_oos_at
    FROM obs
    JOIN price_history ph ON ph.listing_id = obs.listing_id
    WHERE obs.first_seen_at IS NOT NULL
      AND NOT ph.in_stock
      AND ph.observed_at > obs.first_seen_at
    GROUP BY obs.listing_id, obs.first_seen_at
  ),
  vel AS (
    SELECT
      f.listing_id,
      f.first_seen_at,
      f.first_oos_at,
      -- Last in-stock observation BEFORE that first OOS — pairs with first_oos_at
      -- to bound the cadence gap in which the piece actually went. Always >=
      -- first_seen_at (that in-stock row itself qualifies), so the invariant
      -- first_seen_at <= last_in_stock_at < first_oos_at holds by construction.
      (
        SELECT MAX(ph.observed_at)
        FROM price_history ph
        WHERE ph.listing_id = f.listing_id
          AND ph.in_stock
          AND ph.observed_at < f.first_oos_at
      ) AS last_in_stock_at
    FROM firstoos f
  )
  SELECT
    q.id, q.vendor_id, q.named_coral_id,
    q.first_seen_at, q.last_in_stock_at, q.first_oos_at, q.prior_run_finished_at,
    q.raw_title, q.image_url, q.product_url, q.current_price,
    q.vendor_slug, q.vendor_display_name,
    q.named_coral_canonical_name, q.named_coral_slug
  FROM (
    SELECT
      oos.id, oos.vendor_id, oos.named_coral_id,
      vel.first_seen_at, vel.last_in_stock_at, vel.first_oos_at,
      oos.raw_title, oos.image_url, oos.product_url, oos.current_price,
      v.slug            AS vendor_slug,
      v.display_name    AS vendor_display_name,
      nc.canonical_name AS named_coral_canonical_name,
      nc.slug           AS named_coral_slug,
      -- Last SUCCESSFUL scrape that COMPLETED before our first in-stock sighting.
      -- Doubles as (a) the cold-start gate — NULL means no run proves we watched it
      -- appear (replaces the prior EXISTS; identical predicate), dropped by the
      -- outer WHERE; and (b) the render's lifespan anchor (window = first_oos_at -
      -- prior_run_finished_at). See 0046 header (2).
      (
        SELECT MAX(sr.finished_at)
        FROM scraper_runs sr
        WHERE sr.vendor_id = oos.vendor_id
          AND sr.status = 'success'
          AND sr.finished_at IS NOT NULL
          AND sr.finished_at < vel.first_seen_at
      ) AS prior_run_finished_at
    FROM vel
    JOIN oos ON oos.id = vel.listing_id
    JOIN vendors v ON v.id = oos.vendor_id
      AND v.active = true AND v.slug NOT LIKE '!_%' ESCAPE '!'   -- CTK-213 test/inactive-vendor exclusion
    JOIN named_corals nc ON nc.id = oos.named_coral_id
    -- Optional recency selector on the gone-event (NOT a scrape interval): NULL =
    -- all gone pieces; a caller wanting "gone this week" passes 7.
    WHERE (p_window_days IS NULL
           OR vel.first_oos_at >= now() - make_interval(days => p_window_days))
  ) q
  -- Cold-start exclusion: keep only listings a prior successful run proves we
  -- watched appear. Same gate the EXISTS enforced, now surfacing the anchor.
  WHERE q.prior_run_finished_at IS NOT NULL
  -- id tiebreaker: first_oos_at alone is not a total order (a batch scrape writes
  -- the same observed_at for many rows), so a top-N slice render-side would
  -- otherwise be non-reproducible. Mirrors get_cross_vendor_cheapest's determinism.
  ORDER BY q.first_oos_at DESC, q.id DESC;
$function$;


-- ===== get_cross_vendor_cheapest =====
CREATE OR REPLACE FUNCTION public.get_cross_vendor_cheapest()
 RETURNS TABLE(id bigint, vendor_id smallint, named_coral_id integer, current_price numeric, compare_at_price numeric, in_stock boolean, auction_end_time timestamp with time zone, raw_title text, image_url text, product_url text, vendor_slug text, vendor_display_name text, named_coral_canonical_name text, named_coral_slug text)
 LANGUAGE sql
 STABLE
AS $function$
  WITH eligible AS (
    SELECT
      vl.id, vl.vendor_id, vl.named_coral_id, vl.current_price, vl.compare_at_price,
      vl.in_stock, vl.auction_end_time, vl.raw_title, vl.image_url, vl.product_url
    FROM vendor_listings vl
    JOIN vendors av ON av.id = vl.vendor_id                       -- CTK-213
      AND av.active = true AND av.slug NOT LIKE '!_%' ESCAPE '!'  -- CTK-213 test/inactive-vendor exclusion
    WHERE vl.named_coral_id IS NOT NULL
      AND vl.in_stock = true
      AND vl.auction_end_time IS NULL            -- INV-05 residual (D-3)
      AND vl.current_price IS NOT NULL           -- OOS/phantom guard
      AND (vl.category IS NULL OR vl.category <> ALL(ARRAY['equipment','invert']::text[]))  -- INV-07 (CTK-197); CTK-212 + invert -- NULL-safe (keeps NULL-category corals)
  ),
  coral_stats AS (
    SELECT
      named_coral_id,
      MIN(current_price)        AS min_price,
      COUNT(DISTINCT vendor_id) AS vendor_count
    FROM eligible
    GROUP BY named_coral_id
  )
  SELECT
    e.id, e.vendor_id, e.named_coral_id, e.current_price, e.compare_at_price,
    e.in_stock, e.auction_end_time, e.raw_title, e.image_url, e.product_url,
    v.slug              AS vendor_slug,
    v.display_name      AS vendor_display_name,
    nc.canonical_name   AS named_coral_canonical_name,
    nc.slug             AS named_coral_slug
  FROM eligible e
  JOIN coral_stats s ON s.named_coral_id = e.named_coral_id
  JOIN vendors v ON v.id = e.vendor_id
  JOIN named_corals nc ON nc.id = e.named_coral_id
  -- >= 2 distinct vendors carry the coral, and this row is at the cheapest price.
  -- Equality against the group MIN keeps ALL rows at a genuine tie (both ARE the
  -- cheapest) — mirrors cross_vendor_cheapest_ids's tie semantic exactly.
  WHERE s.vendor_count >= 2
    AND e.current_price = s.min_price
  ORDER BY e.named_coral_id, e.current_price, e.vendor_id;
$function$;


-- ===== get_most_restocked =====
CREATE OR REPLACE FUNCTION public.get_most_restocked(p_window_hours integer DEFAULT 168, p_limit integer DEFAULT 10)
 RETURNS TABLE(named_coral_id integer, named_coral_canonical_name text, named_coral_slug text, restock_count bigint)
 LANGUAGE sql
 STABLE
AS $function$
  SELECT
    le.named_coral_id,
    le.named_coral_canonical_name,
    le.named_coral_slug,
    COUNT(*)::bigint AS restock_count
  FROM get_listing_lead_event(NULL, p_window_hours, ARRAY['back-in-stock'], NULL) le
  JOIN vendor_listings vl ON vl.id = le.id
  JOIN vendors av ON av.id = vl.vendor_id                         -- CTK-213
    AND av.active = true AND av.slug NOT LIKE '!_%' ESCAPE '!'  -- CTK-213 test/inactive-vendor exclusion
  WHERE le.named_coral_id IS NOT NULL
    AND (vl.category IS NULL OR vl.category <> ALL(ARRAY['equipment','invert']::text[]))  -- INV-07 (CTK-197); CTK-212 + invert -- NULL-safe (keeps NULL-category corals)
  GROUP BY le.named_coral_id, le.named_coral_canonical_name, le.named_coral_slug
  ORDER BY restock_count DESC, le.named_coral_canonical_name ASC
  LIMIT p_limit;
$function$;


-- ===== get_vendor_drop_cadence =====
CREATE OR REPLACE FUNCTION public.get_vendor_drop_cadence(p_vendor_slug text)
 RETURNS TABLE(history_days integer, organic_drop_count integer, last_organic_drop_at timestamp with time zone, median_scrape_gap_hours numeric, dow_sun integer, dow_mon integer, dow_tue integer, dow_wed integer, dow_thu integer, dow_fri integer, dow_sat integer, qualifies_for_histogram boolean)
 LANGUAGE sql
 STABLE
AS $function$
  WITH v AS (
    SELECT id FROM vendors WHERE slug = p_vendor_slug
  ),
  -- Watch history span: now - first successful scrape. Observation span, NOT the
  -- organic-drop span — a quiet vendor still carries long history. Sourced from
  -- scraper_runs (immune to listing pruning) and consistent with the gap CTE.
  watch AS (
    SELECT (now()::date - MIN(sr.finished_at)::date)::int AS history_days
    FROM scraper_runs sr
    JOIN v ON v.id = sr.vendor_id
    WHERE sr.status = 'success'
      AND sr.finished_at IS NOT NULL
  ),
  -- Honest-organic drops over the vendor's full watch history (window spans ~10y
  -- to cover everything since onboarding). guarded just-listed + INV-07 + INV-08.
  organic AS (
    SELECT
      le.first_seen_at,
      EXTRACT(DOW FROM le.first_seen_at AT TIME ZONE 'UTC')::int AS dow
    FROM get_f7_arrivals_guarded(24 * 3650, ARRAY['just-listed']) le
    JOIN vendor_listings vl ON vl.id = le.id
    JOIN vendors av ON av.id = vl.vendor_id                       -- CTK-213
      AND av.active = true AND av.slug NOT LIKE '!_%' ESCAPE '!'  -- CTK-213 test/inactive-vendor exclusion
    WHERE le.vendor_slug = p_vendor_slug
      AND (vl.category IS NULL OR vl.category <> ALL(ARRAY['equipment','invert']::text[]))  -- INV-07 (CTK-197); CTK-212 + invert -- NULL-safe (keeps NULL-category corals)
      AND vl.bulk_cluster = false                    -- INV-08
  ),
  agg AS (
    SELECT
      COUNT(*)::int                            AS organic_drop_count,
      MAX(first_seen_at)                       AS last_organic_drop_at,
      COUNT(*) FILTER (WHERE dow = 0)::int     AS dow_sun,
      COUNT(*) FILTER (WHERE dow = 1)::int     AS dow_mon,
      COUNT(*) FILTER (WHERE dow = 2)::int     AS dow_tue,
      COUNT(*) FILTER (WHERE dow = 3)::int     AS dow_wed,
      COUNT(*) FILTER (WHERE dow = 4)::int     AS dow_thu,
      COUNT(*) FILTER (WHERE dow = 5)::int     AS dow_fri,
      COUNT(*) FILTER (WHERE dow = 6)::int     AS dow_sat
    FROM organic
  ),
  -- Median scrape gap (hours) over the last 14d of successful runs — the cadence
  -- regularity signal the histogram gate leans on.
  gaps AS (
    SELECT
      EXTRACT(EPOCH FROM (
        sr.finished_at - LAG(sr.finished_at) OVER (ORDER BY sr.finished_at)
      )) / 3600.0 AS gap_h
    FROM scraper_runs sr
    JOIN v ON v.id = sr.vendor_id
    WHERE sr.status = 'success'
      AND sr.finished_at IS NOT NULL
      AND sr.finished_at >= now() - interval '14 days'
  ),
  gap AS (
    SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY gap_h) AS median_gap_h
    FROM gaps
    WHERE gap_h IS NOT NULL
  )
  SELECT
    w.history_days,
    a.organic_drop_count,
    a.last_organic_drop_at,
    round(g.median_gap_h::numeric, 2) AS median_scrape_gap_hours,
    a.dow_sun, a.dow_mon, a.dow_tue, a.dow_wed, a.dow_thu, a.dow_fri, a.dow_sat,
    (
      w.history_days >= 42
      AND g.median_gap_h IS NOT NULL
      AND g.median_gap_h <= 6
      AND a.organic_drop_count >= 15
    ) AS qualifies_for_histogram
  FROM watch w
  CROSS JOIN agg a
  CROSS JOIN gap g;
$function$;
