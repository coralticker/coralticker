-- CTK-011 session 1 pre-step — parameterize get_listing_lead_event()'s
-- fleet-wide row cap.
--
-- 0028 hardcoded LIMIT 100. The 2026-06-02 smoke returned 98 rows on a
-- 24h fleet-wide window — one busy day from silently truncating any
-- caller on the listing_ids IS NULL path. The CTK-011 Discord daily
-- digest is a public broadcast surface; silent truncation there is
-- wrong-info shape for an aggregator (CTK-011 plan §Risks).
--
-- Ratified fix (Jon 2026-06-04, decision register row #76 amendment:
-- parameterize over raise-the-constant):
--
--   row_limit int DEFAULT 100 — fourth parameter.
--     - Existing 3-arg callers (/new + cross-surface medal per #76
--       behavior matrix, lib/queries/listings.ts:134,642) keep current
--       behavior via the default; no code change required.
--     - The digest caller passes an explicit higher limit
--       (get_listing_lead_event(NULL, 24, NULL, 500) per CTK-011 plan)
--       or NULL for uncapped — LIMIT NULL is LIMIT ALL per Postgres
--       semantics.
--
-- Body is UNCHANGED from 0028 except LIMIT 100 -> LIMIT row_limit.
-- Signature widen forces DROP + CREATE (parameter-list change; CREATE
-- OR REPLACE rejects it). GRANTs re-asserted post-CREATE against the
-- 4-arg signature, same grantee set as 0028.
--
-- get_recent_price_drops() — NOT touched here. Its LIMIT 100 serves
-- /deals' event-monotype semantic; no broadcast caller, no saturation
-- evidence. Re-evaluate only if /deals shows the same 98/100 pressure.

DROP FUNCTION IF EXISTS get_listing_lead_event(bigint[], int, text[]);

CREATE FUNCTION get_listing_lead_event(
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
      AND vl.auction_end_time IS NULL                     -- INV-05 #4 (arm-scoped)
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
