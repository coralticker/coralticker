-- CTK-161 D-1 — owned-data content engine: the shared cross-vendor data-query
-- layer as a set of Postgres functions (the design-once unit per D-1: the three
-- consumers — CTK-161 IG/Python, CTK-162 blog/TS, CTK-163 TikTok-YT/Python —
-- straddle a language boundary, so the only single-implementation point is the
-- database). Each content-data computation lands as a STABLE function returning
-- a stable row shape; thin per-language fetch wrappers sit on top.
--
-- Three CREATE FUNCTIONs ship here (all new — CREATE FUNCTION, no return-type
-- widen, so no DROP+CREATE):
--
--   1. get_cross_vendor_cheapest() — promotes the cross-vendor cheapest RANKING
--      from Python (scrapers/tools/ig_select.py's cross_vendor_cheapest_ids +
--      fetch_cross_vendor_cheapest) to SQL so the TS site (CTK-162) gets the same
--      implementation. min(current_price) per named_coral across >= 2 DISTINCT
--      vendors; a genuine price tie keeps >1 crowned id. COMPARATIVE format
--      (D-2) — render names who's cheapest; publish-gated, but the COMPUTATION
--      is ungated and shared (it already powers a score weight inside ig_select).
--
--   2. get_aggregate_activity(window_hours) — lead-event count + distinct-vendor
--      count over a window ("47 drops across 11 shops today"). NON-comparative.
--
--   3. get_most_restocked(window_hours, limit) — back-in-stock lead-events grouped
--      by named_coral over a window, ranked by count ("most restocked this week").
--      NON-comparative.
--
-- Single-listing drop magnitude reuses get_recent_price_drops() AS-IS (D-2) — no
-- new function. Velocity (time-to-OOS) is OUT of scope this migration (resolution
-- floors at scrape cadence + OOS-cause is ambiguous; pending Jon ratification).
--
-- ─── INV-05 (auction state) binding ───
--
-- get_cross_vendor_cheapest runs over the FULL vendor_listings population (not an
-- arm of get_listing_lead_event), so it re-asserts the INV-05 residual triple
-- INDEPENDENTLY in its WHERE: in_stock = true AND auction_end_time IS NULL AND
-- current_price IS NOT NULL. This is the same defense-in-depth predicate the
-- Python guard (content_queries.is_cross_vendor_eligible) re-asserts over the
-- returned rows. No auction is ever crowned "cheapest"; no sold-out or
-- price-on-request row is crowned.
--
-- get_aggregate_activity + get_most_restocked build OVER get_listing_lead_event
-- and inherit its arm-scoped INV-05 binding for free (price-dropped arm carries
-- auction_end_time IS NULL inside the function; back-in-stock + just-listed are
-- auction-orthogonal by design — migrations 0028/0030). Neither is a
-- price/markdown-bearing surface, so no residual predicate is owed.
--
-- ─── row_limit = uncapped is load-bearing for the aggregate count ───
--
-- get_aggregate_activity passes row_limit = NULL (LIMIT ALL) to
-- get_listing_lead_event. The default 100-row cap would SILENTLY UNDERCOUNT a
-- busy day (the 2026-06-02 smoke already saw 98 rows on a 24h fleet window per
-- migration 0030). An aggregate stat that caps at 100 is wrong-info shape.
--
-- ─── Idempotency + apply path ───
--
-- All three are CREATE OR REPLACE FUNCTION (re-runnable; no signature/return-type
-- change to force DROP+CREATE). Apply via scripts/apply_migration_0038.py
-- (mirrors apply_migration_0037.py: scrapers.common.db.get_conn + cursor.execute
-- against NEON_DATABASE_URL per architecture-v1.md decision #65 / CTK-061).
-- GRANT EXECUTE re-asserted post-CREATE, same grantee set as 0028/0030.


-- ─── 1. get_cross_vendor_cheapest — cross-vendor cheapest ranking (COMPARATIVE) ───
--
-- Promotes cross_vendor_cheapest_ids (Python) to SQL. Returns the crowned listing
-- line(s) per named_coral: the row(s) at min(current_price) among >= 2 distinct
-- vendors carrying that coral. in_stock + auction_end_time are projected so the
-- Python fetch-guard can re-assert the eligibility triple per returned row.
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


-- ─── 2. get_aggregate_activity — lead-event + distinct-vendor counts (NON-comparative) ───
--
-- "47 drops across 11 shops today": COUNT(*) lead-events + COUNT(DISTINCT vendor)
-- over the window. Built over get_listing_lead_event(NULL, hours, NULL, NULL) —
-- row_limit NULL (uncapped) so the count is the TRUE fleet count, not capped at
-- the default 100 (see header note). Always returns exactly one row (0/0 on an
-- empty window). Population scope: ALL lead-events, matched + unmatched — DIFFERS
-- from get_most_restocked's matched-only scope by design (see that function).
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
    COUNT(*)::bigint                  AS event_count,
    COUNT(DISTINCT le.vendor_id)::bigint AS vendor_count,
    p_window_hours                    AS window_hours
  FROM get_listing_lead_event(NULL, p_window_hours, NULL, NULL) le;
$$;

GRANT EXECUTE ON FUNCTION get_aggregate_activity(int) TO service_role, authenticated, anon;


-- ─── 3. get_most_restocked — back-in-stock ranking by named_coral (NON-comparative) ───
--
-- "Most restocked this week": back-in-stock LEAD-events grouped by named_coral
-- over the window, ranked by count. event_filter = ['back-in-stock'] selects
-- listings whose canon LEAD event IS back-in-stock (the lead-event-absolute
-- semantic, migration 0028 — not "any back-in-stock event in window").
--
-- POPULATION SCOPE — matched-only (named_coral_id IS NOT NULL). You can't rank a
-- coral you can't name (D-2 "ranks corals"); a raw_title fallback would group
-- vendor-specific title noise (the same coral won't co-group across vendors).
-- This is a NARROWER population than get_aggregate_activity (which counts ALL
-- lead-events) — intentional, NOT an undercount. Fires rarely while the matcher
-- covers ~20/91 named corals; same sparsity posture as the cross-vendor signal.
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
  WHERE le.named_coral_id IS NOT NULL
  GROUP BY le.named_coral_id, le.named_coral_canonical_name, le.named_coral_slug
  ORDER BY restock_count DESC, le.named_coral_canonical_name ASC
  LIMIT p_limit;
$$;

GRANT EXECUTE ON FUNCTION get_most_restocked(int, int) TO service_role, authenticated, anon;
