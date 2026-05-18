-- CTK-040 Session 3 — get_recent_arrivals() RPC backing the /new feed view.
--
-- Wraps the UNION two-arm CTE specced at site.md §4.4 lines 1240-1293
-- (new_listings + back_in_stock arms, server-merged in a single round trip,
-- ordered by event_at DESC, LIMIT 100). PostgREST doesn't surface CTEs
-- through .from().select(), so the query lands as a SQL function called via
-- supabase.rpc('get_recent_arrivals'). The CTE stays inline inside the
-- function per site.md §4.3 lines 1163-1164 precedent (events not yet
-- promoted to a reusable VIEW; that's a successor-ticket call when a second
-- view needs the same window-comparison helper).
--
-- year_introduced omitted from the named_corals projection per Q-040-11
-- hold-position 2026-05-14 (hosted named_corals lacks the column; restore
-- when /lead-architect schema-divergence audit Q-040-12 lands). Aligns with
-- lib/queries/listings.ts LISTING_SELECT shape.
--
-- back_in_stock predicate vl.first_seen_at <= now() - 24h is the dedup seam
-- (avoids double-counting a listing that just-listed AND went OOS-then-back-
-- in-stock all inside the 24h window — just-listed catches that row).
--
-- Idempotent per CTK-028/032/033/034 convention: CREATE OR REPLACE FUNCTION
-- ensures re-run safety; signature change forces DROP + CREATE.
--
-- STABLE volatility — function reads tables and depends on now() within the
-- statement, but produces no side effects. Per Postgres docs: STABLE is
-- correct for SELECT-only functions whose results don't change within a
-- single transaction.

CREATE OR REPLACE FUNCTION get_recent_arrivals()
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
  event text,
  event_at timestamptz,
  vendor_slug text,
  vendor_display_name text,
  named_coral_canonical_name text,
  named_coral_slug text,
  named_coral_origin_vendor text
)
LANGUAGE sql
STABLE
AS $$
  WITH new_listings AS (
    SELECT
      vl.id, vl.vendor_id, vl.raw_title, vl.current_price, vl.in_stock,
      vl.image_url, vl.product_url, vl.first_seen_at, vl.named_coral_id, vl.match_confidence,
      'just-listed'::text  AS event,
      vl.first_seen_at     AS event_at
    FROM vendor_listings vl
    WHERE vl.first_seen_at > now() - interval '24 hours'
      AND vl.in_stock = true
  ),
  restock_events AS (
    SELECT DISTINCT ON (ph.listing_id) ph.listing_id, ph.observed_at
    FROM price_history ph
    WHERE ph.observed_at > now() - interval '24 hours'
      AND ph.in_stock = true
      AND EXISTS (
        SELECT 1 FROM price_history prev
        WHERE prev.listing_id = ph.listing_id
          AND prev.observed_at < ph.observed_at
          AND prev.in_stock = false
      )
    ORDER BY ph.listing_id, ph.observed_at ASC
  ),
  back_in_stock AS (
    SELECT
      vl.id, vl.vendor_id, vl.raw_title, vl.current_price, vl.in_stock,
      vl.image_url, vl.product_url, vl.first_seen_at, vl.named_coral_id, vl.match_confidence,
      'back-in-stock'::text  AS event,
      re.observed_at         AS event_at
    FROM restock_events re
    JOIN vendor_listings vl ON vl.id = re.listing_id
    WHERE vl.in_stock = true
      AND vl.first_seen_at <= now() - interval '24 hours'
  ),
  events AS (
    SELECT * FROM new_listings
    UNION ALL
    SELECT * FROM back_in_stock
  )
  SELECT
    e.id, e.vendor_id, e.raw_title, e.current_price, e.in_stock,
    e.image_url, e.product_url, e.first_seen_at, e.named_coral_id, e.match_confidence,
    e.event, e.event_at,
    v.slug              AS vendor_slug,
    v.display_name      AS vendor_display_name,
    nc.canonical_name   AS named_coral_canonical_name,
    nc.slug             AS named_coral_slug,
    nc.origin_vendor    AS named_coral_origin_vendor
  FROM events e
  JOIN vendors v ON v.id = e.vendor_id
  LEFT JOIN named_corals nc ON nc.id = e.named_coral_id
  ORDER BY e.event_at DESC
  LIMIT 100;
$$;

-- PostgREST needs explicit EXECUTE grant per role calling the function.
-- service_role bypasses RLS but still needs the function grant. anon +
-- authenticated covered for future client-side / authenticated read paths.
GRANT EXECUTE ON FUNCTION get_recent_arrivals() TO service_role, authenticated, anon;
