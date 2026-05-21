-- CTK-061 — fix get_recent_price_drops() 24h LAG-window scope bug.
--
-- Failure mode: migration 0008 placed the 24h freshness filter inside the
-- CTE (WHERE ph.observed_at > now() - interval '24 hours'), which scoped
-- LAG()'s input window to rows already inside 24h. A listing with one
-- price_history row inside 24h got prior_price=NULL and fell out at the
-- e.prior_price IS NOT NULL filter — even when it had prior rows from
-- days ago that LAG should have reached back to. Real price-drop events
-- straddle the boundary ("row N from days ago + row N+1 today"), so the
-- bug masked nearly every drop. RPC returned 1 row vs. spec-intent
-- counter-query baseline of 24. Latent since 0008 landed 2026-05-14;
-- surfaced when Phase 1 data volume crossed the gap. Not a CTK-043
-- cutover regression.
--
-- Fix: move the 24h filter from the CTE to the outer SELECT. CTE leaves
-- LAG unbounded over all of price_history (~18k rows at v1, seq-scan cost
-- negligible); outer SELECT keeps e.observed_at > now() - interval
-- '24 hours' alongside the existing new_price < prior_price + auction-
-- filter clauses. All other clauses preserved verbatim from 0008.
-- Full walkthrough lives in .claude/plans/tickets/CTK-061/{plan,results}.md.
--
-- Idempotent per the CTK-028/032/033/034/038/Session-3 convention:
-- CREATE OR REPLACE FUNCTION with unchanged signature.

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
  ORDER BY e.observed_at DESC
  LIMIT 100;
$$;

-- GRANT preserved from 0008; CREATE OR REPLACE doesn't reset privileges,
-- but re-asserting keeps the grant adjacent to the function body for
-- audit clarity.
GRANT EXECUTE ON FUNCTION get_recent_price_drops() TO service_role, authenticated, anon;
