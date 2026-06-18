-- CTK-161 — velocity (listed-and-gone) query: auction double-gate + window anchor.
--
-- REVISES get_velocity_listings (migration 0042). Two changes, folded into one
-- CREATE OR REPLACE (0042 is unapplied head — no point stacking a 0047 on it):
--   1. the auction double-gate (the /lead-backend INV-05 residual), and
--   2. a new returned column, prior_run_finished_at — the render's lifespan anchor.
--
-- ─── (1) Resolves the /lead-backend-flagged INV-05 residual ───
--
-- 0042 EXEMPTED velocity from the auction gate, reasoning
-- that an auction "legitimately goes OOS (relist / close), so an auction we watched
-- appear and go is a valid 'gone' row." That reasoning conflated two different
-- claims and is corrected here.
--
-- ─── Why velocity is NOT exempt (the corrected reading) ───
--
-- Velocity is not an availability claim ("it's gone") — it is a DEMAND / SPEED
-- claim ("listed and gone fast," the "didn't last" punchline). The window the
-- render bounds (first_oos_at - first_seen_at, rounded UP) is read by the audience
-- as "this is how fast demand consumed it."
--
-- An auction is gone when its CLOCK runs out, not when demand consumed it. The
-- listed-to-gone span of an auction measures the auction's scheduled DURATION, not
-- velocity. Crowning an auction a velocity post asserts demand-speed the data does
-- not show — a false-precision overpromise, the same trust-floor class the velocity
-- claim-resolution canon (branding-guide.md §"Velocity claim resolution",
-- 2026-06-16) holds hardest. So velocity carries the same double-gate the other
-- full-population content functions already do:
--
--   - auction_end_time IS NULL  — INV-05 residual (D-3): no real-end-time auction
--     (ReefnBid / CTK-007) crowned for velocity. Its OOS is a scheduled close.
--   - is_auction = false        — CTK-042 ratified gate (is_auction discriminator,
--     migrations 0038/0039, 2026-06-16): excludes end-time-less Shopify pseudo-
--     auctions, which PASS auction_end_time IS NULL but are availability-deceptive;
--     their OOS is bidding mechanics, not a demand-driven sellout.
--
-- Mirrors the get_cross_vendor_carriers (0043) double-gate exactly — both run over
-- the full vendor_listings population (not built on get_listing_lead_event), so the
-- predicates are re-asserted INDEPENDENTLY, not inherited. The gate lives in the
-- `oos` population CTE (the one place the function touches vendor_listings).
--
-- Cost of the gate: velocity drops auction-format candidates. That loss is correct
-- — a velocity post over an auction would be dishonest about why the piece left.
--
-- ─── (2) prior_run_finished_at — the render's lifespan anchor ───
--
-- The render's window is first_oos_at - prior_run_finished_at, rounded UP, where
-- prior_run_finished_at is the last SUCCESSFUL scrape that COMPLETED before our
-- first in-stock sighting. first_seen_at is only when we FIRST SAW the piece in
-- stock — it could have been listed any time after that prior run scanned the
-- vendor's catalog and found it absent. So the run-completion time is the widest
-- HONEST upper bound on "when it could have appeared"; anchoring the window there
-- never claims tighter-than-observed (rounding UP render-side keeps that honest).
--
-- This same scalar REPLACES the old cold-start EXISTS: the predicate is identical
-- (MAX over the same successful-run-finished-before-first_seen set), and a listing
-- with no such run yields NULL -> dropped by the outer WHERE. So one expression now
-- does double duty: the cold-start exclusion gate AND the render anchor. No behavior
-- change to inclusion; only a new column surfaces. Invariant tightens to
-- prior_run_finished_at < first_seen_at <= last_in_stock_at < first_oos_at.
--
-- Everything else in 0042 is unchanged (price_history-sourced timestamps,
-- first-OOS-after-first-seen transition, claim-neutral SQL, determinism order).
--
-- ─── Idempotency + apply path ───
--
-- DROP FUNCTION IF EXISTS + CREATE (re-runnable to the same end state; the DROP is
-- required because the return type widens — see the DDL note below; no table writes,
-- no live caller). Apply via scripts/apply_migration_0046.py (mirrors
-- apply_migration_0042: scrapers.common.db.get_conn against NEON_DATABASE_URL per
-- architecture-v1.md decision #65 / CTK-061). GRANT EXECUTE re-asserted post-CREATE,
-- same grantee set as 0042.


-- DROP + CREATE, NOT CREATE OR REPLACE: adding prior_run_finished_at to RETURNS
-- TABLE changes the function's return type, which REPLACE cannot do ("cannot change
-- return type of existing function"). DROP IF EXISTS makes this re-runnable AND
-- correct whether 0042's 14-column version is already live in prod (dropped, then
-- recreated at 15 columns) or absent (no-op drop). No dependent objects exist (leaf
-- function, no caller yet), so the DROP is safe.
DROP FUNCTION IF EXISTS get_velocity_listings(int);

CREATE FUNCTION get_velocity_listings(p_window_days int DEFAULT NULL)
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
    -- Auction double-gate (see header): an auction's OOS is its clock, not demand,
    -- so it cannot carry a velocity (speed-of-sale) claim.
    SELECT
      vl.id, vl.vendor_id, vl.named_coral_id, vl.raw_title, vl.image_url,
      vl.product_url, vl.current_price
    FROM vendor_listings vl
    WHERE vl.in_stock = false
      AND vl.named_coral_id IS NOT NULL
      AND vl.auction_end_time IS NULL            -- INV-05 residual (D-3)
      AND vl.is_auction = false                  -- CTK-042 pseudo-auction gate
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
      -- prior_run_finished_at). See header (2).
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
