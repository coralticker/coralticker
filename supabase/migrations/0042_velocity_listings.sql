-- CTK-161 — owned-data content engine: velocity (listed-and-gone) query.
--
-- The fifth content-data function, added after velocity cleared publish-now-safe
-- (branding-guide.md §"Velocity claim resolution- + cause-honesty", 2026-06-16) —
-- superseding the 0041-header "OUT of scope / pending Jon ratification" note. Same
-- D-1 shape as 0041: a STABLE function returning a stable row shape, a thin
-- per-language fetch wrapper on top (content_queries.fetch_velocity).
--
-- ─── What it exposes (and what it deliberately does NOT) ───
--
-- One row per still-OOS, matched listing whose full first lifecycle we OBSERVED.
-- Three raw timestamps per row, nothing derived:
--
--   first_seen_at     — first real-time in-stock observation
--   last_in_stock_at  — last in-stock observation BEFORE the first OOS transition
--   first_oos_at      — first in-stock = false transition
--
-- The RENDER (CTK-164) derives everything claim-bearing from these, self-contained
-- per row, with NO scrape-interval / cron config threaded in:
--   uncertainty window = first_oos_at - last_in_stock_at  (the cadence-bounded gap
--                        in which the piece actually went — we don't know when)
--   lifespan upper-bound = first_oos_at - first_seen_at   (round UP off this)
--
-- SQL stays claim-NEUTRAL. No "sold out" — there is no sellout-vs-delist
-- discriminator column, so cause-neutral templating ("gone" / "didn't last") is a
-- render-side concern, never asserted here.
--
-- ─── Timestamps come from price_history, NOT vendor_listings.first_seen_at ───
--
-- price_history is append-only, one row per (price, in_stock) CHANGE (decision #7),
-- so its observed_at is the true evidence-of-observation moment (this is exactly
-- the re-anchor 0005 used: first_seen_at = MIN(price_history.observed_at)). The
-- vendor_listings.first_seen_at COLUMN is unreliable for a lifespan claim — it is
-- fictional for cold-start rows (set in the past, 0001_init.sql:163) and 0005 left
-- ~35% of catalog rows untouched (no mutation signal, but possibly imprecise). So
-- this function reads the lifecycle straight off price_history.
--
-- ─── Cold-start exclusion — claim-honesty correctness gate, NOT optional ───
--
-- A velocity claim ("listed and gone within {window}") is a lie about any listing
-- that was already on the shelf before we ever scraped its vendor: we never saw it
-- appear, so its lifespan is fictional (it could have been listed for months).
-- Keep ONLY listings we genuinely watched appear — proven by a successful scrape of
-- the same vendor that COMPLETED before the first in-stock observation. That run
-- scanned the catalog and this listing was absent; it showed up later. Cold-start /
-- first-scrape listings (present in the vendor's earliest scrape) have no such
-- prior run and are excluded. status = 'success' only: a 'partial' run may not have
-- covered the full catalog, so absence in it is not proof.
--
-- ─── INV-05 (auction state) ───
--
-- No residual predicate owed. Velocity is not a price/markdown-bearing surface (it
-- ranks nothing on price and crowns no "cheapest"); current_price is projected for
-- the render but never compared. Auctions legitimately go OOS (relist / close), so
-- an auction that we watched appear and go is a valid "gone" row — no auction gate.
--
-- ─── Idempotency + apply path ───
--
-- CREATE OR REPLACE FUNCTION (re-runnable; new function, no signature change).
-- Apply via scripts/apply_migration_0042.py (mirrors apply_migration_0041.py:
-- scrapers.common.db.get_conn + cursor.execute against NEON_DATABASE_URL per
-- architecture-v1.md decision #65 / CTK-061). GRANT EXECUTE re-asserted post-CREATE,
-- same grantee set as 0041.


CREATE OR REPLACE FUNCTION get_velocity_listings(p_window_days int DEFAULT NULL)
RETURNS TABLE (
  id bigint,
  vendor_id smallint,
  named_coral_id integer,
  first_seen_at timestamptz,
  last_in_stock_at timestamptz,
  first_oos_at timestamptz,
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
    SELECT
      vl.id, vl.vendor_id, vl.named_coral_id, vl.raw_title, vl.image_url,
      vl.product_url, vl.current_price
    FROM vendor_listings vl
    WHERE vl.in_stock = false
      AND vl.named_coral_id IS NOT NULL
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
    oos.id, oos.vendor_id, oos.named_coral_id,
    vel.first_seen_at, vel.last_in_stock_at, vel.first_oos_at,
    oos.raw_title, oos.image_url, oos.product_url, oos.current_price,
    v.slug            AS vendor_slug,
    v.display_name    AS vendor_display_name,
    nc.canonical_name AS named_coral_canonical_name,
    nc.slug           AS named_coral_slug
  FROM vel
  JOIN oos ON oos.id = vel.listing_id
  JOIN vendors v ON v.id = oos.vendor_id
  JOIN named_corals nc ON nc.id = oos.named_coral_id
  -- Cold-start exclusion (see header) — keep only listings we watched appear.
  WHERE EXISTS (
    SELECT 1 FROM scraper_runs sr
    WHERE sr.vendor_id = oos.vendor_id
      AND sr.status = 'success'
      AND sr.finished_at IS NOT NULL
      AND sr.finished_at < vel.first_seen_at
  )
  -- Optional recency selector on the gone-event (NOT a scrape interval): NULL =
  -- all gone pieces; a caller wanting "gone this week" passes 7.
  AND (p_window_days IS NULL
       OR vel.first_oos_at >= now() - make_interval(days => p_window_days))
  ORDER BY vel.first_oos_at DESC;
$$;

GRANT EXECUTE ON FUNCTION get_velocity_listings(int) TO service_role, authenticated, anon;
