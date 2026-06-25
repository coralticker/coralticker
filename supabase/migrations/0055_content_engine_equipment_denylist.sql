-- CTK-197 (Tier 1B) — equipment denylist across the IG content-engine count
-- surfaces. INV-07 cadence #1: every surface that derives a count / aggregate /
-- headline from vendor_listings excludes equipment via the NULL-safe denylist
--
--   category IS DISTINCT FROM 'equipment'
--
-- NOT a coral-allowlist (category IN (...corals)). An allowlist would drop the
-- ~308 NULL-category trade-name corals per CTK-194 — trading one trust hit for a
-- bigger coverage hit. Denylist only; equipment is the single category excluded.
--
-- ─── What this fixes (live audit, /lead-backend 2026-06-25, read-only) ───
--
-- CTK-186 added the denylist to 9 web read spots; CTK-195 (migration 0054) added
-- it to the F7 IG cover + /new?window=week feed. The IG content-engine count
-- functions (migrations 0041/0046) CTK-186 never reached still derive counts from
-- vendor_listings with no equipment filter. The audit:
--
--   get_aggregate_activity  (0041) — ALL lead-events (matched + UNMATCHED) over a
--                                     window. LIVE LEAK: 168h window = 1 equipment
--                                     event / 3561; 24h = 0 / 36. The sole free leak.
--   get_velocity_listings   (0046) — matched-only (oos CTE: named_coral_id NOT NULL).
--                                     Clean today (62 rows, 0 equipment). Gate = D-i-D.
--   get_cross_vendor_cheapest (0041) — matched-only (eligible CTE). Clean (0 rows). D-i-D.
--   get_most_restocked      (0041) — matched-only (named_coral_id NOT NULL). Clean
--                                     (0 matched-equipment fleet-wide). D-i-D.
--
-- SELECT count(*) FROM vendor_listings WHERE named_coral_id IS NOT NULL
--   AND category='equipment' = 0 (any stock). The three matched-only functions
-- cannot leak equipment today — no equipment row carries a named_coral_id. But the
-- matched-only guarantee is only as strong as the matcher's precision, and CTK-189
-- proved equipment CAN acquire a coral signal via title keywords. The NULL-safe gate
-- (zero cost) closes that latent reverse-FP hole and expresses INV-07 uniformly
-- across all four count surfaces.
--
-- ─── Join-back gotcha ───
--
-- get_listing_lead_event does NOT project category. get_aggregate_activity and
-- get_most_restocked build over it, so the gate is added as a join-back to
-- vendor_listings on the returned id (1:1 — the lead-event function returns at most
-- one row per listing, so the join neither inflates COUNT(*) nor the restock GROUP).
-- get_velocity_listings and get_cross_vendor_cheapest touch vendor_listings directly
-- (the oos / eligible CTEs), so the predicate is added inline there.
--
-- Consumer-side denylist (matches CTK-186's TS-layer philosophy). The predicate is
-- deliberately NOT pushed into the shared get_listing_lead_event — wide blast radius
-- across every consumer, out of scope for a bounded 1B.
--
-- ─── Idempotency + apply path ───
--
-- All four are CREATE OR REPLACE FUNCTION — no signature / return-type change, so no
-- DROP needed; re-runnable to the same end state. Bodies are reproduced verbatim from
-- 0041 / 0046 with only the equipment predicate added. Apply via
-- scripts/apply_migration_0055.py (mirrors apply_migration_0046.py:
-- scrapers.common.db.get_conn against NEON_DATABASE_URL per architecture-v1.md
-- decision #65 / CTK-061). GRANT EXECUTE re-asserted post-CREATE, same grantee set.


-- ─── 1. get_aggregate_activity — the live leak (join-back gate) ───
--
-- Counts ALL lead-events (matched + unmatched) over a window. get_listing_lead_event
-- does not project category, so join back to vendor_listings on the returned id and
-- exclude equipment. The join is 1:1 (one lead-event row per listing), so COUNT(*)
-- and COUNT(DISTINCT vendor_id) stay the true fleet counts minus equipment.
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
  WHERE vl.category IS DISTINCT FROM 'equipment';   -- INV-07 (CTK-197)
$$;

GRANT EXECUTE ON FUNCTION get_aggregate_activity(int) TO service_role, authenticated, anon;


-- ─── 2. get_velocity_listings — denylist in the oos CTE (defense-in-depth) ───
--
-- matched-only (oos CTE requires named_coral_id IS NOT NULL) — clean today, but the
-- gate is added inline to the one place the function touches vendor_listings. Body is
-- byte-identical to migration 0046 except the new vl.category predicate in `oos`.
CREATE OR REPLACE FUNCTION get_velocity_listings(p_window_days int DEFAULT NULL)
RETURNS TABLE (
  id bigint,
  vendor_id smallint,
  named_coral_id integer,
  first_seen_at timestamptz,
  last_in_stock_at timestamptz,
  first_oos_at timestamptz,
  prior_run_finished_at timestamptz,
  raw_title text,
  image_url text,
  product_url text,
  current_price numeric,
  vendor_slug text,
  vendor_display_name text,
  named_coral_canonical_name text,
  named_coral_slug text
)
LANGUAGE sql
STABLE
AS $$
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
$$;

GRANT EXECUTE ON FUNCTION get_velocity_listings(int) TO service_role, authenticated, anon;


-- ─── 3. get_cross_vendor_cheapest — denylist in the eligible CTE (defense-in-depth) ───
--
-- matched-only (eligible CTE requires named_coral_id IS NOT NULL) — clean today.
-- Body is byte-identical to migration 0041 except the new vl.category predicate in
-- `eligible`, the one place the function touches vendor_listings.
CREATE OR REPLACE FUNCTION get_cross_vendor_cheapest()
RETURNS TABLE (
  id bigint,
  vendor_id smallint,
  named_coral_id integer,
  current_price numeric,
  compare_at_price numeric,
  in_stock boolean,
  auction_end_time timestamptz,
  raw_title text,
  image_url text,
  product_url text,
  vendor_slug text,
  vendor_display_name text,
  named_coral_canonical_name text,
  named_coral_slug text
)
LANGUAGE sql
STABLE
AS $$
  WITH eligible AS (
    SELECT
      vl.id, vl.vendor_id, vl.named_coral_id, vl.current_price, vl.compare_at_price,
      vl.in_stock, vl.auction_end_time, vl.raw_title, vl.image_url, vl.product_url
    FROM vendor_listings vl
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
$$;

GRANT EXECUTE ON FUNCTION get_cross_vendor_cheapest() TO service_role, authenticated, anon;


-- ─── 4. get_most_restocked — join-back gate (defense-in-depth) ───
--
-- matched-only (named_coral_id IS NOT NULL) — clean today (0 matched-equipment). Like
-- get_aggregate_activity, builds over get_listing_lead_event (no category projection),
-- so the gate is a 1:1 join-back to vendor_listings on the returned id. The join does
-- not change the GROUP BY / COUNT — one lead-event row per listing. Body is identical
-- to migration 0041 except the join + predicate. Gated for INV-07 uniformity (every
-- count surface carries the same predicate) and to close the CTK-189 reverse-FP hole.
CREATE OR REPLACE FUNCTION get_most_restocked(
  p_window_hours int DEFAULT 168,
  p_limit int DEFAULT 10
)
RETURNS TABLE (
  named_coral_id integer,
  named_coral_canonical_name text,
  named_coral_slug text,
  restock_count bigint
)
LANGUAGE sql
STABLE
AS $$
  SELECT
    le.named_coral_id,
    le.named_coral_canonical_name,
    le.named_coral_slug,
    COUNT(*)::bigint AS restock_count
  FROM get_listing_lead_event(NULL, p_window_hours, ARRAY['back-in-stock'], NULL) le
  JOIN vendor_listings vl ON vl.id = le.id
  WHERE le.named_coral_id IS NOT NULL
    AND vl.category IS DISTINCT FROM 'equipment'   -- INV-07 (CTK-197)
  GROUP BY le.named_coral_id, le.named_coral_canonical_name, le.named_coral_slug
  ORDER BY restock_count DESC, le.named_coral_canonical_name ASC
  LIMIT p_limit;
$$;

GRANT EXECUTE ON FUNCTION get_most_restocked(int, int) TO service_role, authenticated, anon;
