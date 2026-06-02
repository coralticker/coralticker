-- CTK-099 — add in_stock=true filter to get_recent_price_drops().
--
-- Failure mode: the /deals feed surfaced price drops regardless of
-- current stock state. A listing that dropped in price within the 24h
-- LAG window and subsequently went OOS (carrying a non-null
-- current_price) continued to render as a buyable "deal." Diagnosis
-- 2026-05-31 against live code: get_recent_price_drops() (migration 0009)
-- returned vl.in_stock as a column but had no in_stock predicate; the
-- /deals page + getRecentPriceDrops wrapper had no render-side filter.
-- /new (lib/queries/listings.ts:117) and /vendor/[slug] (:245) both
-- filter WHERE vl.in_stock = true at SQL — /deals was the inconsistent
-- surface. Aggregator-staleness trust floor per
-- feedback_aggregator_staleness_tier_floor.md (same class as the
-- wrong-availability badge that re-tiered CTK-094 to 1A).
--
-- Fix: add AND vl.in_stock = true to the outer SELECT WHERE clause.
-- Body is otherwise verbatim from 0009 (LAG-window scope preserved); the
-- diff is exactly one line. No backfill (query-time only; effect on first
-- call post-apply).
--
-- Scope guard: surgical, single predicate. Auction-state exclusion
-- (auction_end_time IS NULL) is CTK-047 / INV-05 scope and is explicitly
-- out of scope here. INV-05 obligation #2 already flips in_stock=false
-- on closed auctions, so closed auctions drop naturally under the new
-- predicate without a second predicate edit. Architecture lives at
-- architecture-v1.md decision register #70 + coordination-invariants.md
-- INV-05.
--
-- Idempotent per the CTK-028/032/033/034/038/061 convention:
-- CREATE OR REPLACE FUNCTION with unchanged signature.
--
-- ─── Disposition note (added 2026-06-02 at CTK-047 + CTK-109 plan-draft) ───
-- The auction_end_time IS NULL predicate this header punts to CTK-047
-- territory lands at migration 0027 inside the generalized
-- get_listing_drop_context(listing_ids, window_hours) function. CTK-109
-- frontend swaps /deals from get_recent_price_drops() to
-- get_listing_drop_context(NULL, 24) — same row set as today bit-for-bit
-- plus the auction predicate plus compare_at_price in the projection.
-- No rework of 0026's body needed — get_recent_price_drops() stays in
-- place but unused after CTK-109 frontend swap; future cleanup CTK drops
-- it once caller-audit confirms zero remaining callers.

CREATE OR REPLACE FUNCTION get_recent_price_drops()
RETURNS TABLE (
  id bigint,
  vendor_id smallint,
  raw_title text,
  current_price numeric,
  in_stock boolean,
  image_url text,
  product_url text,
  first_seen_at timestamptz,
  named_coral_id integer,
  match_confidence text,
  prior_price numeric,
  observed_at timestamptz,
  vendor_slug text,
  vendor_display_name text,
  named_coral_canonical_name text,
  named_coral_slug text,
  named_coral_origin_vendor text
)
LANGUAGE sql
STABLE
AS $$
  WITH events AS (
    SELECT
      ph.listing_id,
      ph.price AS new_price,
      LAG(ph.price) OVER (PARTITION BY ph.listing_id ORDER BY ph.observed_at) AS prior_price,
      ph.observed_at
    FROM price_history ph
  )
  SELECT
    vl.id, vl.vendor_id, vl.raw_title, vl.current_price, vl.in_stock,
    vl.image_url, vl.product_url, vl.first_seen_at, vl.named_coral_id, vl.match_confidence,
    e.prior_price, e.observed_at,
    v.slug              AS vendor_slug,
    v.display_name      AS vendor_display_name,
    nc.canonical_name   AS named_coral_canonical_name,
    nc.slug             AS named_coral_slug,
    nc.origin_vendor    AS named_coral_origin_vendor
  FROM events e
  JOIN vendor_listings vl ON vl.id = e.listing_id
  JOIN vendors v ON v.id = vl.vendor_id
  LEFT JOIN named_corals nc ON nc.id = vl.named_coral_id
  WHERE e.observed_at > now() - interval '24 hours'
    AND e.new_price IS NOT NULL
    AND e.prior_price IS NOT NULL
    AND e.new_price < e.prior_price
    AND vl.current_price IS NOT NULL
    AND vl.in_stock = true
  ORDER BY e.observed_at DESC
  LIMIT 100;
$$;

-- GRANT preserved from 0009; CREATE OR REPLACE doesn't reset privileges,
-- but re-asserting keeps the grant adjacent to the function body for
-- audit clarity.
GRANT EXECUTE ON FUNCTION get_recent_price_drops() TO service_role, authenticated, anon;
