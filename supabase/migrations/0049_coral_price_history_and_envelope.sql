-- CTK-162 (b) — per-coral price time-series functions for the price-history
-- template at /coral/[slug]/price-history (plan.md scope b, D-1 child route).
--
-- Two STABLE read functions over the append-only price_history table
-- (0001_init.sql:213, decision #7 — one row per observed (price, in_stock)
-- CHANGE, not per scrape). Same D-1 shape as 0041/0042: thin wrappers a TS
-- caller hits through lib/queries/*.ts; the function is the shared contract,
-- the language wrapper is per-consumer (CTK-161 design-once).
--
-- ─── Anchor fork RESOLVED (plan.md Open-item #1) ───
--
-- price_history is complete and authoritative for a coral's full lifespan, so
-- the series is anchored ENTIRELY off price_history — NOT seeded from
-- vendor_listings.current_price. The scraper writes a price_history row on the
-- "new" decision at first-seen (diff.py:419), and cohort-OOS writes its own
-- terminal (last-price, in_stock=false) point (diff.py:339-344). The first and
-- last observations a coral's listings carry are therefore both real
-- price_history rows; there is no opening level to backfill from the live row.
--
-- ─── INV-01 is N/A for these functions ───
--
-- Both return time-series POINTS (observed_at / price / in_stock; day /
-- min_price), not formatDataRow() listing rows. The price-history page's
-- listing list (the vendor cards beside the chart) carries INV-01 separately at
-- the frontend slice; these series functions are below that contract.
--
-- Apply via scripts/apply_migration_0049.py (scrapers.common.db.get_conn per
-- decision #65 / CTK-061; mirrors apply_migration_0046.py). 0048 is the head on
-- disk; this is 0049. Re-runnable: get_coral_price_history is CREATE OR REPLACE;
-- get_coral_price_envelope is DROP IF EXISTS + CREATE (its `day` return type
-- changed date -> text — see its header). No live caller yet (the price-history
-- template is the downstream build). GRANT EXECUTE re-asserted post-CREATE, same
-- grantee set as 0041/0042.
--
-- ─── Window-edge divergence between the two functions (by design, for now) ───
--
-- The two p_window_days edges are NOT the same shape and a windowed render that
-- overlays both must know it:
--   * get_coral_price_envelope windows on a CALENDAR-DAY boundary
--     (current_date - N), because it aligns with generate_series' per-day grid.
--   * get_coral_price_history windows on a ROLLING instant edge
--     (now() - N days), because it filters raw observation timestamps.
-- They can therefore disagree by up to ~1 day at the left edge (a calendar day
-- vs a rolling-clock cutoff). Harmless until a windowed price-history view ships
-- that draws both series on one axis; reconcile the edge then (pick one shape),
-- not now — neither function has a live caller.


-- =============================================================================
-- get_coral_price_history — per-LISTING step series
-- =============================================================================
-- One row per price_history observation, keyed per listing (a vendor may carry
-- two listings of the same coral — they stay separate honest tracks, not
-- merged). in_stock travels per point so the render can break the step line on
-- OOS gaps. p_window_days NULL = full history; else only observations inside
-- the trailing window (filters the points directly — see the windowed-track
-- note below).
--
-- Windowed-track note (flagged to /lead-backend): because price_history is
-- change-only, a listing whose price did not change inside a short window emits
-- no row in that window and so drops out of the windowed per-listing view. The
-- envelope's LOCF (below) still carries that listing into the headline line, so
-- the cross-vendor floor is unaffected; only the per-listing detail track is.
-- If every active listing must appear in a windowed per-listing view, this
-- function needs a pre-window anchor point — a follow-up, not built here.
CREATE OR REPLACE FUNCTION get_coral_price_history(
  p_named_coral_id integer,
  p_window_days integer DEFAULT NULL
)
RETURNS TABLE (
  listing_id   bigint,
  vendor_id    smallint,
  vendor_slug  text,
  observed_at  timestamptz,
  price        numeric,
  in_stock     boolean
)
LANGUAGE sql
STABLE
AS $$
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
  WHERE vl.named_coral_id = p_named_coral_id
    AND (
      p_window_days IS NULL
      OR ph.observed_at >= now() - make_interval(days => p_window_days)
    )
  -- Per-listing, then chronological: the render walks each listing_id's points
  -- in time order to draw its step line.
  ORDER BY ph.listing_id, ph.observed_at;
$$;

GRANT EXECUTE ON FUNCTION get_coral_price_history(integer, integer)
  TO service_role, authenticated, anon;


-- =============================================================================
-- get_coral_price_envelope — cross-vendor daily-min floor (LOCF)
-- =============================================================================
-- The headline line: the cheapest IN-STOCK price across all of the coral's
-- listings, per calendar day. price_history is sparse/change-only, so a naive
-- "rows on day d" read would have holes on every day nothing changed — LOCF
-- (last-observation-carried-forward) fills them: for each day d and each
-- listing, take that listing's latest price_history row AS OF the end of d that
-- is in_stock with a non-null price, then min() across listings.
--
-- NULL-price and OOS listings drop out of the per-day min BY CONSTRUCTION: the
-- LATERAL is an INNER lateral, so a (day, listing) pair where the listing has
-- no in-stock non-null observation as of d produces no row and cannot lower the
-- min. A day on which EVERY listing is OOS/null produces no rows at all for
-- that day -> the day is absent from the output (an honest gap, NOT a zero).
--
-- Window: p_window_days bounds only the generate_series START (current_date -
-- window), NOT the LOCF lookup — the "latest row as of d" still reaches back
-- before the window so the level is carried INTO the window boundary rather
-- than restarting mid-level. NULL = from the coral's first observation.
--
-- `day` is returned as TEXT (YYYY-MM-DD), NOT date: @neondatabase/serverless
-- parses a Postgres `date` into a JS Date (local-midnight), which then tz-shifts
-- to the wrong calendar day under .toISOString() in a non-UTC runtime. Emitting
-- the calendar day as text hands the TS layer a clean string with no Date round
-- trip. (timestamptz in get_coral_price_history stays typed — it is an absolute
-- instant the TS mapper .toISOString()s losslessly; only bare `date` is unsafe.)
--
-- DROP + CREATE (not CREATE OR REPLACE): changing `day` date -> text changes the
-- RETURNS TABLE type, which REPLACE cannot do. DROP IF EXISTS makes apply correct
-- whether the prior date-returning version is live (dropped, recreated as text)
-- or absent (no-op drop). Re-runnable to the same end state; no live caller yet.
DROP FUNCTION IF EXISTS get_coral_price_envelope(integer, integer);

CREATE FUNCTION get_coral_price_envelope(
  p_named_coral_id integer,
  p_window_days integer DEFAULT NULL
)
RETURNS TABLE (
  day       text,
  min_price numeric
)
LANGUAGE sql
STABLE
AS $$
  WITH listings AS (
    SELECT vl.id
    FROM vendor_listings vl
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
$$;

GRANT EXECUTE ON FUNCTION get_coral_price_envelope(integer, integer)
  TO service_role, authenticated, anon;
