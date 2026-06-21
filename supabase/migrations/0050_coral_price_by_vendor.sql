-- CTK-162 (b) — per-VENDOR price time-series for the price-history template at
-- /coral/[slug]/price-history (plan.md scope b, D-1 child route). The third twin
-- alongside 0049's get_coral_price_history (per-listing step) and
-- get_coral_price_envelope (cross-vendor floor).
--
-- ─── Why this function exists, and why it is a near-verbatim envelope clone ───
--
-- The chart draws one line per vendor (vendor's cheapest in-stock price per day)
-- with the cross-vendor floor underneath. The floor is get_coral_price_envelope.
-- This function is that SAME construction with the GROUP grain widened from
-- per-day to per-(day, vendor). That sameness is LOAD-BEARING, not stylistic:
--
--   MIN(min_price) over this function's per-vendor rows for a day
--     ==  get_coral_price_envelope.min_price for that day
--
-- holds BY CONSTRUCTION only if the LATERAL pick + the post-pick gate are byte-
-- identical to the envelope's. The floor is the min of the per-vendor lines, so
-- if the two functions ever picked a different "latest row as of d" or gated
-- differently, the rendered floor would drift off the lines beneath it. Keep the
-- bounds/days CTEs, the LATERAL, and the WHERE gate verbatim against 0049; only
-- the listings CTE (adds vendor_id), the final projection (vendor columns +
-- COUNT), the GROUP BY grain, and the ORDER BY differ. apply_migration_0050.py
-- re-proves the equality live on every apply (consistency-by-construction check).
--
-- ─── INV-05 residual triple / auction exclusion — inherited, verified ───
--
-- Auction listings carry a parse-time NULL current_price ("price on request"),
-- and their price_history rows therefore carry price IS NULL. The post-pick gate
-- `latest.price > 0` drops them before MIN/COUNT (NULL > 0 is unknown -> the row
-- is excluded) — an auction row can never reach the per-vendor min. No auction-
-- specific clause needed; the same in_stock = true AND price > 0 gate that covers
-- the residual triple in 0049 covers it here. (The > 0 superseded the bare
-- IS NOT NULL per CTK-162 /code-review #1, Tier 1A — a $0/negative is a phantom
-- price, never a real line point; it also still excludes NULL.)
--
-- ─── Deferred hardening — rides CTK-179, NOT here ───
--
-- UTC-tz pinning, staleness caps, and span caps are deliberately ABSENT. They
-- ship across both twin functions uniformly under CTK-179; adding them to one
-- twin and not the other would break the floor-equals-min-of-lines invariant
-- above. The `day` text return carries the same serverless-driver tz hazard note
-- as 0049 (a bare `date` tz-shifts under .toISOString() in a non-UTC runtime;
-- emitting YYYY-MM-DD text hands the TS layer a clean string).
--
-- Apply via scripts/apply_migration_0050.py (scrapers.common.db.get_conn per
-- decision #65 / CTK-061; mirrors apply_migration_0049.py). 0049 is the head on
-- disk; this is 0050. Brand-new function -> CREATE OR REPLACE (re-runnable, no
-- type-change DROP needed). No live caller yet (the per-vendor chart is the
-- downstream build) -> no apply-pre-push sequencing gate. GRANT EXECUTE asserted
-- post-CREATE, same grantee set as 0049.


-- =============================================================================
-- get_coral_price_by_vendor — per-vendor daily-min line (LOCF)
-- =============================================================================
-- For each calendar day and each vendor carrying the coral: the cheapest
-- in-stock price across that vendor's listings of the coral, via the same LOCF
-- (last-observation-carried-forward) pick as the envelope. listing_count is how
-- many of that vendor's listings were in-stock with a non-null price that day
-- (post-gate row count) — render can show "3 listings" behind a vendor's point.
--
-- NULL-price / OOS listings drop out of each per-vendor min BY CONSTRUCTION (the
-- LATERAL is INNER + the post-pick gate); a (day, vendor) pair where none of the
-- vendor's listings is in-stock/non-null as of d produces no row -> that vendor
-- is absent for that day (an honest gap in that vendor's line, not a zero), and
-- a day where EVERY vendor is OOS produces no rows at all.
CREATE OR REPLACE FUNCTION get_coral_price_by_vendor(
  p_named_coral_id integer,
  p_window_days integer DEFAULT NULL
)
RETURNS TABLE (
  day           text,
  vendor_id     smallint,
  vendor_slug   text,
  min_price     numeric,
  listing_count integer
)
LANGUAGE sql
STABLE
AS $$
  WITH listings AS (
    -- Delta vs 0049: also carry vendor_id so the per-vendor GROUP grain and the
    -- vendors join below have it without a second pass over vendor_listings.
    SELECT vl.id, vl.vendor_id
    FROM vendor_listings vl
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
$$;

GRANT EXECUTE ON FUNCTION get_coral_price_by_vendor(integer, integer)
  TO service_role, authenticated, anon;
