-- CTK-042 acute auction-leak gate — Tier 1B. Reader-side: gate auction
-- rows out of get_listing_lead_event() across all three arms.
--
-- The launch email digest (CTK-011) calls get_listing_lead_event(NULL, 24,
-- NULL, ...). The CTK-160 auction-keep override re-admitted WWC auctions
-- into the cohort lifecycle (kept + price-nulled), so they now surface as
-- just-listed / back-in-stock lead events: in_stock=true, current_price
-- NULL (renders "price on request"), no auction_end_time. The leak is on
-- the availability axis, not price — CTK-160 de-fanged the deceptive buy
-- price, but the rows still broadcast as live drops.
--
-- Why the existing predicate didn't catch it:
--   - price_drops arm carried `auction_end_time IS NULL` (INV-05 #4). That
--     predicate is INSUFFICIENT for Shopify variant-pseudo-auctions — they
--     have NO extractable end-time, so they PASS `IS NULL` rather than
--     being excluded. (The price_drops arm is independently protected by
--     its `current_price IS NOT NULL` guard, since auctions are nulled —
--     but the discriminator predicate itself is wrong for this class.)
--   - back_in_stock + just_listed arms had NO auction gate at all, and NO
--     current_price guard. just_listed is the primary digest leak: a freshly
--     kept auction (first_seen within window, in_stock) fires just-listed.
--
-- Fix: gate every arm on `vl.is_auction = false` (the CTK-042 discriminator
-- that fires on tag-detected auctions, ratified 2026-06-16). The price_drops
-- arm KEEPS its `auction_end_time IS NULL` and ADDS `is_auction = false` for
-- symmetry + defense-in-depth: the two predicates cover different auction
-- populations (auction_end_time = future real-end-time auctions / ReefnBid
-- CTK-007; is_auction = today's end-time-less Shopify pseudo-auctions).
--
-- LOAD-BEARING APPLY ORDER: migration 0038 (column) -> backfill (sets
-- is_auction=true on the live auction set) -> THIS migration. Applying this
-- before the backfill gates on an all-false column and excludes nothing.
--
-- INV-05 #3 render-gate (auction_end_time IS NOT NULL distinct render) is
-- the deferred CTK-042 tail — NOT touched here. OOS-flip obligation #2 stays
-- on auction_end_time. get_recent_price_drops() (/deals) is NOT touched —
-- out of this acute slice's scope.
--
-- Body is UNCHANGED from migration 0030 except the three arm WHERE clauses.
-- CREATE OR REPLACE (same 4-arg signature as 0030 — no DROP needed; the
-- signature and RETURNS shape are byte-identical). GRANTs re-asserted to
-- match 0030's grantee set. 0033/0035 touch get_recent_price_drops, a
-- different function — 0030 is the current get_listing_lead_event def.

CREATE OR REPLACE FUNCTION get_listing_lead_event(
  listing_ids bigint[] DEFAULT NULL,
  window_hours int DEFAULT 24,
  event_filter text[] DEFAULT NULL,
  row_limit int DEFAULT 100
)
RETURNS TABLE (
  id bigint,
  vendor_id smallint,
  raw_title text,
  current_price numeric,
  compare_at_price numeric,
  in_stock boolean,
  image_url text,
  product_url text,
  first_seen_at timestamptz,
  named_coral_id integer,
  match_confidence text,
  event text,
  event_at timestamptz,
  prior_price numeric,
  vendor_slug text,
  vendor_display_name text,
  named_coral_canonical_name text,
  named_coral_slug text,
  named_coral_origin_vendor text
)
LANGUAGE sql
STABLE
AS $$
  WITH price_drops AS (
    SELECT
      e.listing_id,
      'price-dropped'::text AS event,
      e.observed_at         AS event_at,
      e.prior_price,
      1                     AS precedence_rank
    FROM (
      SELECT
        ph.listing_id,
        ph.price AS new_price,
        LAG(ph.price) OVER (PARTITION BY ph.listing_id ORDER BY ph.observed_at) AS prior_price,
        ph.observed_at
      FROM price_history ph
    ) e
    JOIN vendor_listings vl ON vl.id = e.listing_id
    WHERE e.observed_at > now() - (window_hours * interval '1 hour')
      AND e.new_price IS NOT NULL
      AND e.prior_price IS NOT NULL
      AND e.new_price < e.prior_price
      AND vl.current_price IS NOT NULL
      AND vl.in_stock = true
      AND vl.auction_end_time IS NULL                     -- INV-05 #4 (real-end-time auctions)
      AND vl.is_auction = false                           -- CTK-042 (end-time-less pseudo-auctions)
      AND (listing_ids IS NULL OR e.listing_id = ANY(listing_ids))
  ),
  back_in_stock AS (
    SELECT DISTINCT ON (e.listing_id)
      e.listing_id,
      'back-in-stock'::text AS event,
      e.observed_at         AS event_at,
      NULL::numeric         AS prior_price,
      2                     AS precedence_rank
    FROM (
      SELECT
        ph.listing_id,
        ph.observed_at,
        ph.in_stock,
        LAG(ph.in_stock)    OVER (PARTITION BY ph.listing_id ORDER BY ph.observed_at) AS prior_in_stock,
        LAG(ph.observed_at) OVER (PARTITION BY ph.listing_id ORDER BY ph.observed_at) AS prior_observed_at
      FROM price_history ph
    ) e
    JOIN vendor_listings vl ON vl.id = e.listing_id
    WHERE e.observed_at > now() - (window_hours * interval '1 hour')
      AND e.in_stock = true
      AND e.prior_in_stock = false
      -- Semantic threshold on OOS duration before restock; intentionally
      -- not scaled with window_hours per Q-NEW-D 2026-06-02.
      AND (e.observed_at - e.prior_observed_at) >= interval '24 hours'
      AND vl.in_stock = true
      AND vl.is_auction = false                           -- CTK-042 auction-leak gate
      AND (listing_ids IS NULL OR e.listing_id = ANY(listing_ids))
    ORDER BY e.listing_id, e.observed_at ASC
  ),
  just_listed AS (
    SELECT
      vl.id                AS listing_id,
      'just-listed'::text  AS event,
      vl.first_seen_at     AS event_at,
      NULL::numeric        AS prior_price,
      3                    AS precedence_rank
    FROM vendor_listings vl
    WHERE vl.first_seen_at > now() - (window_hours * interval '1 hour')
      AND vl.in_stock = true
      AND vl.is_auction = false                           -- CTK-042 auction-leak gate (primary digest leak)
      AND (listing_ids IS NULL OR vl.id = ANY(listing_ids))
  ),
  events AS (
    SELECT * FROM price_drops
    UNION ALL
    SELECT * FROM back_in_stock
    UNION ALL
    SELECT * FROM just_listed
  ),
  ranked AS (
    SELECT
      e.*,
      ROW_NUMBER() OVER (
        PARTITION BY e.listing_id
        ORDER BY e.precedence_rank, e.event_at DESC
      ) AS rn
    FROM events e
  )
  SELECT
    vl.id, vl.vendor_id, vl.raw_title, vl.current_price, vl.compare_at_price, vl.in_stock,
    vl.image_url, vl.product_url, vl.first_seen_at, vl.named_coral_id, vl.match_confidence,
    r.event, r.event_at, r.prior_price,
    v.slug              AS vendor_slug,
    v.display_name      AS vendor_display_name,
    nc.canonical_name   AS named_coral_canonical_name,
    nc.slug             AS named_coral_slug,
    nc.origin_vendor    AS named_coral_origin_vendor
  FROM ranked r
  JOIN vendor_listings vl ON vl.id = r.listing_id
  JOIN vendors v ON v.id = vl.vendor_id
  LEFT JOIN named_corals nc ON nc.id = vl.named_coral_id
  WHERE r.rn = 1
    -- event_filter is a post-rank selector over lead-events, not a
    -- candidate-set restriction; preserves canon lead-event-absolute
    -- semantic per Q-NEW-C 2026-06-02. event_filter=['back-in-stock']
    -- returns listings whose lead per canon IS back-in-stock — not
    -- "listings with any back-in-stock event in window."
    AND (event_filter IS NULL OR r.event = ANY(event_filter))
  ORDER BY r.event_at DESC
  -- row_limit NULL = uncapped (LIMIT NULL is LIMIT ALL); default 100
  -- preserves 0028 behavior for existing callers.
  LIMIT row_limit;
$$;

GRANT EXECUTE ON FUNCTION get_listing_lead_event(bigint[], int, text[], int) TO service_role, authenticated, anon;
