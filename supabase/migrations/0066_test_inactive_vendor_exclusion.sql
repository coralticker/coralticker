-- CTK-213 (Tier 1A) — test/inactive-vendor exclusion at the SQL-function layer.
--
-- Root cause: the CTK-095 belt-filter `active = true AND slug NOT LIKE '!_%'
-- ESCAPE '!'` only ever lived in the TS vendor-LIST queries (lib/queries/
-- vendors.ts, the /vendors index). The entire vendor_listings SQL-function family
-- powering /new, /coral, price-history, vendor pages, cross-vendor counts, IG
-- counts, and the digest email never carried it. A 2026-06-28 test insert (2,511
-- listings under 10 inactive `_ctk%test` vendors) made the gap glaring: 2,509 test
-- rows were reachable through get_listing_lead_event alone (/new + the digest).
--
-- Fix: add `active = true AND slug NOT LIKE '!_%' ESCAPE '!'` to the vendors join
-- of all 13 functions. All test vendors are active=false, so the active clause
-- alone clears every test row immediately; the slug belt-filter is defense-in-depth
-- against an active=true test vendor (mirrors the CTK-095 web-query convention,
-- ESCAPE char `!` per vendors.ts).
--
-- Placement: the predicate sits at the EARLIEST vendor_listings scan per function
-- (source CTE) where the function aggregates across vendors — get_coral_price_
-- envelope (MIN floor, no vendors join at all pre-CTK-213) and get_cross_vendor_
-- cheapest (vendor_count >= 2 gate) would otherwise let an inactive test vendor
-- pollute the aggregate even with the test ROW dropped at projection. Where a
-- function emits one row per listing with no cross-vendor aggregation, the predicate
-- sits on the existing final vendors join. Bodies are otherwise verbatim from the
-- live pg_get_functiondef dump (2026-06-29).
--
-- All CREATE OR REPLACE, unchanged signatures — grants are preserved, and each
-- GRANT EXECUTE is re-asserted per the RPC convention (architecture-v1.md #65).
--
-- get_f7_arrivals_guarded is NOT edited: it is a thin wrapper over
-- f7_arrivals_dispositioned (fixed here), so it inherits the filter transitively.
--
-- Scope guard: filter-only. The INV-05 `is_auction = false` add to
-- get_recent_price_drops is a deliberate fast-follow, NOT bundled here.
--
-- Apply: python -m scripts.apply_migration 66


CREATE OR REPLACE FUNCTION public.get_listing_lead_event(listing_ids bigint[] DEFAULT NULL::bigint[], window_hours integer DEFAULT 24, event_filter text[] DEFAULT NULL::text[], row_limit integer DEFAULT 100)
 RETURNS TABLE(id bigint, vendor_id smallint, raw_title text, current_price numeric, compare_at_price numeric, in_stock boolean, image_url text, product_url text, first_seen_at timestamp with time zone, named_coral_id integer, match_confidence text, event text, event_at timestamp with time zone, prior_price numeric, vendor_slug text, vendor_display_name text, named_coral_canonical_name text, named_coral_slug text, named_coral_origin_vendor text)
 LANGUAGE sql
 STABLE
AS $function$
  WITH price_drops AS (
    SELECT
      e.listing_id,
      'price-dropped'::text AS event,
      e.observed_at         AS event_at,
      e.prior_price,
      1                     AS precedence_rank
    FROM (
      SELECT
        ph.listing_id,
        ph.price AS new_price,
        LAG(ph.price) OVER (PARTITION BY ph.listing_id ORDER BY ph.observed_at) AS prior_price,
        ph.observed_at
      FROM price_history ph
    ) e
    JOIN vendor_listings vl ON vl.id = e.listing_id
    WHERE e.observed_at > now() - (window_hours * interval '1 hour')
      AND e.new_price IS NOT NULL
      AND e.prior_price IS NOT NULL
      AND e.new_price < e.prior_price
      AND vl.current_price IS NOT NULL
      AND vl.in_stock = true
      AND vl.auction_end_time IS NULL                     -- INV-05 #4 (real-end-time auctions)
      AND vl.is_auction = false                           -- CTK-042 (end-time-less pseudo-auctions)
      AND (listing_ids IS NULL OR e.listing_id = ANY(listing_ids))
  ),
  back_in_stock AS (
    SELECT DISTINCT ON (e.listing_id)
      e.listing_id,
      'back-in-stock'::text AS event,
      e.observed_at         AS event_at,
      NULL::numeric         AS prior_price,
      2                     AS precedence_rank
    FROM (
      SELECT
        ph.listing_id,
        ph.observed_at,
        ph.in_stock,
        LAG(ph.in_stock)    OVER (PARTITION BY ph.listing_id ORDER BY ph.observed_at) AS prior_in_stock,
        LAG(ph.observed_at) OVER (PARTITION BY ph.listing_id ORDER BY ph.observed_at) AS prior_observed_at
      FROM price_history ph
    ) e
    JOIN vendor_listings vl ON vl.id = e.listing_id
    WHERE e.observed_at > now() - (window_hours * interval '1 hour')
      AND e.in_stock = true
      AND e.prior_in_stock = false
      -- Semantic threshold on OOS duration before restock; intentionally
      -- not scaled with window_hours per Q-NEW-D 2026-06-02.
      AND (e.observed_at - e.prior_observed_at) >= interval '24 hours'
      AND vl.in_stock = true
      AND vl.is_auction = false                           -- CTK-042 auction-leak gate
      AND (listing_ids IS NULL OR e.listing_id = ANY(listing_ids))
    ORDER BY e.listing_id, e.observed_at ASC
  ),
  just_listed AS (
    SELECT
      vl.id                AS listing_id,
      'just-listed'::text  AS event,
      vl.first_seen_at     AS event_at,
      NULL::numeric        AS prior_price,
      3                    AS precedence_rank
    FROM vendor_listings vl
    WHERE vl.first_seen_at > now() - (window_hours * interval '1 hour')
      AND vl.in_stock = true
      AND vl.is_auction = false                           -- CTK-042 auction-leak gate (primary digest leak)
      AND (listing_ids IS NULL OR vl.id = ANY(listing_ids))
  ),
  events AS (
    SELECT * FROM price_drops
    UNION ALL
    SELECT * FROM back_in_stock
    UNION ALL
    SELECT * FROM just_listed
  ),
  ranked AS (
    SELECT
      e.*,
      ROW_NUMBER() OVER (
        PARTITION BY e.listing_id
        ORDER BY e.precedence_rank, e.event_at DESC
      ) AS rn
    FROM events e
  )
  SELECT
    vl.id, vl.vendor_id, vl.raw_title, vl.current_price, vl.compare_at_price, vl.in_stock,
    vl.image_url, vl.product_url, vl.first_seen_at, vl.named_coral_id, vl.match_confidence,
    r.event, r.event_at, r.prior_price,
    v.slug              AS vendor_slug,
    v.display_name      AS vendor_display_name,
    nc.canonical_name   AS named_coral_canonical_name,
    nc.slug             AS named_coral_slug,
    nc.origin_vendor    AS named_coral_origin_vendor
  FROM ranked r
  JOIN vendor_listings vl ON vl.id = r.listing_id
  JOIN vendors v ON v.id = vl.vendor_id
    AND v.active = true AND v.slug NOT LIKE '!_%' ESCAPE '!'   -- CTK-213 test/inactive-vendor exclusion
  LEFT JOIN named_corals nc ON nc.id = vl.named_coral_id
  WHERE r.rn = 1
    -- event_filter is a post-rank selector over lead-events, not a
    -- candidate-set restriction; preserves canon lead-event-absolute
    -- semantic per Q-NEW-C 2026-06-02. event_filter=['back-in-stock']
    -- returns listings whose lead per canon IS back-in-stock — not
    -- "listings with any back-in-stock event in window."
    AND (event_filter IS NULL OR r.event = ANY(event_filter))
  ORDER BY r.event_at DESC
  -- row_limit NULL = uncapped (LIMIT NULL is LIMIT ALL); default 100
  -- preserves 0028 behavior for existing callers.
  LIMIT row_limit;
$function$;
GRANT EXECUTE ON FUNCTION get_listing_lead_event(bigint[], integer, text[], integer) TO service_role, authenticated, anon;

CREATE OR REPLACE FUNCTION public.get_coral_price_by_vendor(p_named_coral_id integer, p_window_days integer DEFAULT NULL::integer)
 RETURNS TABLE(day text, vendor_id smallint, vendor_slug text, min_price numeric, listing_count integer)
 LANGUAGE sql
 STABLE
AS $function$
  WITH listings AS (
    -- Delta vs 0049: also carry vendor_id so the per-vendor GROUP grain and the
    -- vendors join below have it without a second pass over vendor_listings.
    SELECT vl.id, vl.vendor_id
    FROM vendor_listings vl
    JOIN vendors av ON av.id = vl.vendor_id                       -- CTK-213
      AND av.active = true AND av.slug NOT LIKE '!_%' ESCAPE '!'  -- CTK-213 test/inactive-vendor exclusion
    WHERE vl.named_coral_id = p_named_coral_id
  ),
  bounds AS (
    -- Verbatim from get_coral_price_envelope. Series start = first observed day,
    -- clamped up to the window floor when a window is given. Empty-history yields
    -- an empty result by either branch (NULL start -> days guard yields no rows;
    -- windowed -> GREATEST ignores the NULL min -> days generate but the gate
    -- drops every pair).
    SELECT
      CASE
        WHEN p_window_days IS NULL THEN MIN(ph.observed_at)::date
        ELSE GREATEST(MIN(ph.observed_at)::date, current_date - p_window_days)
      END AS start_day
    FROM price_history ph
    JOIN listings l ON l.id = ph.listing_id
  ),
  days AS (
    SELECT generate_series(b.start_day, current_date, interval '1 day')::date AS d
    FROM bounds b
    WHERE b.start_day IS NOT NULL
  )
  SELECT
    days.d::text         AS day,
    l.vendor_id          AS vendor_id,
    v.slug               AS vendor_slug,
    MIN(latest.price)    AS min_price,
    COUNT(*)::integer    AS listing_count
  FROM days
  CROSS JOIN listings l
  JOIN vendors v ON v.id = l.vendor_id
  CROSS JOIN LATERAL (
    -- Verbatim from get_coral_price_envelope (the LOAD-BEARING sameness): this
    -- listing's LATEST state as of end-of-day d, regardless of stock — latest row
    -- at or before midnight of d+1. Stock/price are gated AFTER the pick (the
    -- WHERE below), not inside it, so a newer OOS/null flip correctly drops the
    -- listing instead of leaving a stale in-stock price contributing to the min.
    -- ph.id DESC breaks observed_at ties (batch scrape shares a timestamp) so the
    -- pick is deterministic and matches the Python recompute in
    -- apply_migration_0050.py (which sorts observed_at DESC, id DESC).
    SELECT ph.price, ph.in_stock
    FROM price_history ph
    WHERE ph.listing_id = l.id
      AND ph.observed_at < days.d + 1
    ORDER BY ph.observed_at DESC, ph.id DESC
    LIMIT 1
  ) latest
  -- Verbatim gate. Honest-gap property preserved per (day, vendor).
  WHERE latest.in_stock = true
    AND latest.price > 0  -- $0/negative is a phantom price, never a real line point (CTK-162 /code-review #1, Tier 1A); matches the 0049 envelope twin
  GROUP BY days.d, l.vendor_id, v.slug
  -- Vendor-major per the CTK-162 (b) directive spec: each vendor's line is a
  -- contiguous run in time order, ready for the chart to draw line-by-line. The
  -- consumer regroups either way; this matches the written contract.
  ORDER BY l.vendor_id, days.d;
$function$;
GRANT EXECUTE ON FUNCTION get_coral_price_by_vendor(integer, integer) TO service_role, authenticated, anon;

CREATE OR REPLACE FUNCTION public.get_coral_price_envelope(p_named_coral_id integer, p_window_days integer DEFAULT NULL::integer)
 RETURNS TABLE(day text, min_price numeric)
 LANGUAGE sql
 STABLE
AS $function$
  WITH listings AS (
    SELECT vl.id
    FROM vendor_listings vl
    JOIN vendors av ON av.id = vl.vendor_id                       -- CTK-213
      AND av.active = true AND av.slug NOT LIKE '!_%' ESCAPE '!'  -- CTK-213 test/inactive-vendor exclusion
    WHERE vl.named_coral_id = p_named_coral_id
  ),
  bounds AS (
    -- Series start = first observed day, clamped up to the window floor when a
    -- window is given. Empty-history outcome (coral never observed) is still an
    -- empty result, but reached differently per branch:
    --   * NULL window: MIN(observed_at) NULL -> NULL start_day -> the days CTE's
    --     `start_day IS NOT NULL` guard yields no rows.
    --   * windowed: GREATEST IGNORES NULL args, so GREATEST(NULL, current_date -
    --     N) = current_date - N (non-null) -> days generates a range, but the
    --     in-stock gate below drops every (day, listing) pair -> still empty.
    SELECT
      CASE
        WHEN p_window_days IS NULL THEN MIN(ph.observed_at)::date
        ELSE GREATEST(MIN(ph.observed_at)::date, current_date - p_window_days)
      END AS start_day
    FROM price_history ph
    JOIN listings l ON l.id = ph.listing_id
  ),
  days AS (
    SELECT generate_series(b.start_day, current_date, interval '1 day')::date AS d
    FROM bounds b
    WHERE b.start_day IS NOT NULL
  )
  SELECT
    days.d::text AS day,
    MIN(latest.price) AS min_price
  FROM days
  CROSS JOIN listings l
  CROSS JOIN LATERAL (
    -- This listing's LATEST state as of end-of-day d, regardless of stock —
    -- latest row at or before midnight of d+1. Stock/price are gated AFTER the
    -- pick (below), not inside it: filtering to in_stock here would pick the
    -- last in-stock row and ignore a NEWER OOS flip, leaving a delisted listing
    -- contributing its stale last price to the floor. Picking the true latest
    -- row then gating means a later OOS/null state correctly drops the listing.
    -- ph.id DESC breaks ties when two rows share an observed_at (batch scrape
    -- writes the same timestamp across rows) so the pick is deterministic and
    -- matches the Python recompute in apply_migration_0049.py (which sorts the
    -- same way); without it the LOCF level on a tied day could flap.
    SELECT ph.price, ph.in_stock
    FROM price_history ph
    WHERE ph.listing_id = l.id
      AND ph.observed_at < days.d + 1
    ORDER BY ph.observed_at DESC, ph.id DESC
    LIMIT 1
  ) latest
  -- Honest-gap property preserved: a day where every listing's LATEST state is
  -- OOS/null contributes no rows -> the day is absent from the output.
  WHERE latest.in_stock = true
    AND latest.price > 0  -- $0/negative is a phantom price, never a real floor (CTK-162 /code-review #1, Tier 1A); supersedes the bare IS NOT NULL
  GROUP BY days.d
  ORDER BY days.d;
$function$;
GRANT EXECUTE ON FUNCTION get_coral_price_envelope(integer, integer) TO service_role, authenticated, anon;

CREATE OR REPLACE FUNCTION public.get_coral_price_history(p_named_coral_id integer, p_window_days integer DEFAULT NULL::integer)
 RETURNS TABLE(listing_id bigint, vendor_id smallint, vendor_slug text, observed_at timestamp with time zone, price numeric, in_stock boolean)
 LANGUAGE sql
 STABLE
AS $function$
  SELECT
    ph.listing_id,
    vl.vendor_id,
    v.slug AS vendor_slug,
    ph.observed_at,
    ph.price,
    ph.in_stock
  FROM vendor_listings vl
  JOIN price_history ph ON ph.listing_id = vl.id
  JOIN vendors v        ON v.id = vl.vendor_id
    AND v.active = true AND v.slug NOT LIKE '!_%' ESCAPE '!'   -- CTK-213 test/inactive-vendor exclusion
  WHERE vl.named_coral_id = p_named_coral_id
    AND (
      p_window_days IS NULL
      OR ph.observed_at >= now() - make_interval(days => p_window_days)
    )
  -- Per-listing, then chronological: the render walks each listing_id's points
  -- in time order to draw its step line.
  ORDER BY ph.listing_id, ph.observed_at;
$function$;
GRANT EXECUTE ON FUNCTION get_coral_price_history(integer, integer) TO service_role, authenticated, anon;

CREATE OR REPLACE FUNCTION public.get_cross_vendor_carriers()
 RETURNS TABLE(id bigint, vendor_id smallint, named_coral_id integer, current_price numeric, in_stock boolean, image_url text, product_url text, event_at timestamp with time zone, vendor_slug text, vendor_display_name text, named_coral_canonical_name text, named_coral_slug text)
 LANGUAGE sql
 STABLE
AS $function$
  SELECT
    vl.id, vl.vendor_id, vl.named_coral_id, vl.current_price,
    vl.in_stock, vl.image_url, vl.product_url,
    vl.first_seen_at    AS event_at,           -- the 'listed' event time F9 orders on
    v.slug              AS vendor_slug,
    v.display_name      AS vendor_display_name,
    nc.canonical_name   AS named_coral_canonical_name,
    nc.slug             AS named_coral_slug
  FROM vendor_listings vl
  JOIN vendors v ON v.id = vl.vendor_id
    AND v.active = true AND v.slug NOT LIKE '!_%' ESCAPE '!'   -- CTK-213 test/inactive-vendor exclusion
  JOIN named_corals nc ON nc.id = vl.named_coral_id
  WHERE vl.named_coral_id IS NOT NULL
    AND vl.in_stock = true
    AND vl.auction_end_time IS NULL            -- INV-05 residual (D-3)
    AND vl.is_auction = false                  -- CTK-042 pseudo-auction availability gate
  ORDER BY vl.named_coral_id, vl.first_seen_at DESC, vl.id DESC;  -- vl.id DESC = total-order tiebreak (#2)
$function$;
GRANT EXECUTE ON FUNCTION get_cross_vendor_carriers() TO service_role, authenticated, anon;

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
      AND vl.category IS DISTINCT FROM 'equipment'  -- INV-07 (CTK-197)
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
GRANT EXECUTE ON FUNCTION get_cross_vendor_cheapest() TO service_role, authenticated, anon;

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
    AND vl.category IS DISTINCT FROM 'equipment'   -- INV-07 (CTK-197)
  GROUP BY le.named_coral_id, le.named_coral_canonical_name, le.named_coral_slug
  ORDER BY restock_count DESC, le.named_coral_canonical_name ASC
  LIMIT p_limit;
$function$;
GRANT EXECUTE ON FUNCTION get_most_restocked(integer, integer) TO service_role, authenticated, anon;

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
      AND vl.category IS DISTINCT FROM 'equipment'  -- INV-07 (CTK-197)
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
GRANT EXECUTE ON FUNCTION get_velocity_listings(integer) TO service_role, authenticated, anon;

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
      AND vl.category IS DISTINCT FROM 'equipment'   -- INV-07
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
GRANT EXECUTE ON FUNCTION get_vendor_drop_cadence(text) TO service_role, authenticated, anon;

CREATE OR REPLACE FUNCTION public.get_vendor_recent_drops(p_vendor_slug text, p_window_days integer DEFAULT 60, p_limit integer DEFAULT NULL::integer)
 RETURNS TABLE(id bigint, vendor_id smallint, raw_title text, current_price numeric, compare_at_price numeric, in_stock boolean, image_url text, product_url text, first_seen_at timestamp with time zone, named_coral_id integer, match_confidence text, event text, event_at timestamp with time zone, prior_price numeric, vendor_slug text, vendor_display_name text, named_coral_canonical_name text, named_coral_slug text, named_coral_origin_vendor text)
 LANGUAGE sql
 STABLE
AS $function$
  SELECT
    le.id, le.vendor_id, le.raw_title, le.current_price, le.compare_at_price, le.in_stock,
    le.image_url, le.product_url, le.first_seen_at, le.named_coral_id, le.match_confidence,
    le.event, le.event_at, le.prior_price, le.vendor_slug, le.vendor_display_name,
    le.named_coral_canonical_name, le.named_coral_slug, le.named_coral_origin_vendor
  FROM get_f7_arrivals_guarded(p_window_days * 24, ARRAY['just-listed']) le
  JOIN vendor_listings vl ON vl.id = le.id
  JOIN vendors av ON av.id = vl.vendor_id                         -- CTK-213
    AND av.active = true AND av.slug NOT LIKE '!_%' ESCAPE '!'  -- CTK-213 test/inactive-vendor exclusion
  WHERE le.vendor_slug = p_vendor_slug
    AND vl.category IS DISTINCT FROM 'equipment'   -- INV-07
    AND vl.bulk_cluster = false                    -- INV-08
  ORDER BY le.first_seen_at DESC
  LIMIT p_limit;
$function$;
GRANT EXECUTE ON FUNCTION get_vendor_recent_drops(text, integer, integer) TO service_role, authenticated, anon;

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
  WHERE vl.category IS DISTINCT FROM 'equipment'   -- INV-07 (CTK-197)
    AND vl.bulk_cluster = false;                   -- INV-08 (CTK-198 item #4)
$function$;
GRANT EXECUTE ON FUNCTION get_aggregate_activity(integer) TO service_role, authenticated, anon;

CREATE OR REPLACE FUNCTION public.get_recent_price_drops(p_window_days integer)
 RETURNS TABLE(id bigint, vendor_id smallint, raw_title text, current_price numeric, compare_at_price numeric, in_stock boolean, image_url text, product_url text, first_seen_at timestamp with time zone, named_coral_id integer, match_confidence text, prior_price numeric, event_at timestamp with time zone, vendor_slug text, vendor_display_name text, named_coral_canonical_name text, named_coral_slug text, named_coral_origin_vendor text)
 LANGUAGE sql
 STABLE
AS $function$
  WITH drop_events AS (
    -- Arm 1 — CT-observed drops. Body verbatim from 0028's canon LAG
    -- CTE; interval parameterized to p_window_days (0033).
    SELECT
      e.listing_id,
      e.prior_price,
      e.observed_at AS event_at,
      1             AS precedence_rank
    FROM (
      SELECT
        ph.listing_id,
        ph.price AS new_price,
        LAG(ph.price) OVER (PARTITION BY ph.listing_id ORDER BY ph.observed_at) AS prior_price,
        ph.observed_at
      FROM price_history ph
    ) e
    JOIN vendor_listings vl ON vl.id = e.listing_id
    WHERE e.observed_at > now() - (p_window_days * interval '1 day')
      AND e.new_price IS NOT NULL
      AND e.prior_price IS NOT NULL
      AND e.new_price < e.prior_price
      AND vl.current_price IS NOT NULL
      AND vl.in_stock = true                              -- INV-05 (arm-scoped)
      AND vl.auction_end_time IS NULL                     -- INV-05 (arm-scoped)
  ),
  markdown_events AS (
    -- Arm 2 — active vendor markdowns with attested onset in-window,
    -- at or above the 5% card-gate floor (change (c)).
    SELECT
      vl.id                  AS listing_id,
      NULL::numeric          AS prior_price,
      vl.markdown_started_at AS event_at,
      2                      AS precedence_rank
    FROM vendor_listings vl
    WHERE vl.compare_at_price >= vl.current_price * 1.05
      AND vl.markdown_started_at > now() - (p_window_days * interval '1 day')
      AND vl.in_stock = true                              -- INV-05 (arm-scoped)
      AND vl.auction_end_time IS NULL                     -- INV-05 (arm-scoped)
  ),
  ranked AS (
    -- One row per listing; price-dropped precedence per 0028 canon.
    SELECT
      u.*,
      ROW_NUMBER() OVER (
        PARTITION BY u.listing_id
        ORDER BY u.precedence_rank, u.event_at DESC
      ) AS rn
    FROM (
      SELECT * FROM drop_events
      UNION ALL
      SELECT * FROM markdown_events
    ) u
  )
  SELECT
    vl.id, vl.vendor_id, vl.raw_title, vl.current_price, vl.compare_at_price, vl.in_stock,
    vl.image_url, vl.product_url, vl.first_seen_at, vl.named_coral_id, vl.match_confidence,
    r.prior_price, r.event_at,
    v.slug              AS vendor_slug,
    v.display_name      AS vendor_display_name,
    nc.canonical_name   AS named_coral_canonical_name,
    nc.slug             AS named_coral_slug,
    nc.origin_vendor    AS named_coral_origin_vendor
  FROM ranked r
  JOIN vendor_listings vl ON vl.id = r.listing_id
  JOIN vendors v ON v.id = vl.vendor_id
    AND v.active = true AND v.slug NOT LIKE '!_%' ESCAPE '!'   -- CTK-213 test/inactive-vendor exclusion
  LEFT JOIN named_corals nc ON nc.id = vl.named_coral_id
  WHERE r.rn = 1
  ORDER BY r.event_at DESC, r.listing_id                  -- change (a): total order
$function$;
GRANT EXECUTE ON FUNCTION get_recent_price_drops(integer) TO service_role, authenticated, anon;

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
GRANT EXECUTE ON FUNCTION f7_arrivals_dispositioned(integer, text[]) TO service_role, authenticated, anon;
