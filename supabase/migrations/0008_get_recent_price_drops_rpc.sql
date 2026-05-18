-- CTK-040 Session 4 — get_recent_price_drops() RPC backing the /deals feed view.
--
-- Wraps the LAG-window CTE specced at site.md §4.3 lines 1135-1160
-- (per-listing PARTITION BY listing_id LAG over price_history, then filter
-- where new_price IS NOT NULL AND prior_price IS NOT NULL AND new_price <
-- prior_price; ORDER BY observed_at DESC LIMIT 100). PostgREST doesn't
-- surface LAG window functions through .from().select(), so the query
-- lands as a SQL function called via supabase.rpc('get_recent_price_drops').
-- Mirrors Session 3's migration 0007 cadence (UNION CTE / get_recent_arrivals
-- RPC) — both are the same architectural pattern: SQL CTE expressivity that
-- PostgREST cannot host directly.
--
-- Auction-listing filter per Q-040-14 (Decisions locked Session 4 2026-05-14):
-- belt-and-suspenders vl.current_price IS NOT NULL at the outer SELECT WHERE.
-- Per project_auctions_in_scope.md 2026-05-14, auction listings carry
-- current_price = NULL at parse-time. The existing e.new_price IS NOT NULL
-- AND e.prior_price IS NOT NULL clauses MAY already filter auction noise IF
-- arch-v1 §1.5 #7 reliably writes the null-current-price price_history row
-- on auction-state-flip transitions, but a "$45 → null → $40" sequence
-- where price_history skipped the null row would surface a fake "$45 → $40"
-- drop via LAG. Belt-and-suspenders adds one clause; cheap insurance vs. a
-- reactive CTK-XXX scaffold if production surfaces a ghost drop. Filter at
-- final SELECT requires the current listing state is buy-price-shape, not
-- auction-shape; precedes Phase 2 CTK-042 auction-state rendering work.
--
-- year_introduced omitted from the named_corals projection per Q-040-11
-- hold-position 2026-05-14 (hosted named_corals lacks the column; restore
-- when /lead-architect schema-divergence audit Q-040-12 lands). Aligns with
-- migration 0007 + lib/queries/listings.ts LISTING_SELECT shape.
--
-- Idempotent per CTK-028/032/033/034/038/Session-3 convention: CREATE OR
-- REPLACE FUNCTION ensures re-run safety; signature change forces DROP +
-- CREATE.
--
-- STABLE volatility — function reads tables and depends on now() within the
-- statement, but produces no side effects. Per Postgres docs: STABLE is
-- correct for SELECT-only functions whose results don't change within a
-- single transaction.

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
    WHERE ph.observed_at > now() - interval '24 hours'
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
  WHERE e.new_price IS NOT NULL
    AND e.prior_price IS NOT NULL
    AND e.new_price < e.prior_price
    AND vl.current_price IS NOT NULL
  ORDER BY e.observed_at DESC
  LIMIT 100;
$$;

-- PostgREST needs explicit EXECUTE grant per role calling the function.
-- service_role bypasses RLS but still needs the function grant. anon +
-- authenticated covered for future client-side / authenticated read paths.
GRANT EXECUTE ON FUNCTION get_recent_price_drops() TO service_role, authenticated, anon;
