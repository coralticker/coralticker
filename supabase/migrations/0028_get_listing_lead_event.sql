-- CTK-047 B-1 (Q2 amendment) + CTK-109 — precedence-aware lead-event RPC.
-- Supersedes migration 0027's get_listing_drop_context() function shape.
--
-- Three CREATE statements ship here:
--
--   1. DROP get_listing_drop_context() — orphan from 0027. No production
--      callers ever wired in; /backend-engineer Session 2 verified the
--      function shape but the directive amended (Q2 brand-canon lock
--      2026-06-02 — lead-event precedence rule: price-dropped >
--      back-in-stock > just-listed) before any consumer migrated. Drop
--      with zero blast radius. 0027's ALTER TABLE auction_end_time + the
--      get_recent_arrivals widen + the rest of the migration's applied
--      state PRESERVED — 0027 stays as historical record per apply-
--      immutability discipline.
--
--   2. NEW get_listing_lead_event(listing_ids bigint[], window_hours int,
--      event_filter text[]) — three-arm UNION + ROW_NUMBER precedence
--      ranking. One row per listing, lead event only.
--
--   3. DROP + CREATE get_recent_price_drops() — adds compare_at_price to
--      projection (CTK-109 /deals half) + AND vl.auction_end_time IS NULL
--      to outer WHERE (INV-05 #4, monotype-function variant). Signature
--      widen (return-type extends) forces DROP + CREATE; CREATE OR REPLACE
--      rejects return-type changes per Postgres docs. GRANT re-asserted
--      post-CREATE.
--
-- get_recent_arrivals() — NOT touched here. Kept live in this migration
-- to avoid the code/DB deploy race: PR that lands 0028 + the /new
-- code switch to get_listing_lead_event ships together; between migration
-- apply and Vercel deploy, /new still calls get_recent_arrivals; if 0028
-- dropped it, /new would 500 during that window. Sequencing:
--
--     0028 (this migration) — ships function design.
--     PR with 0028 + /new code switch — apply migration, switch /new,
--       deploy frontend. Both atomic-from-the-user-perspective.
--     0029 (follow-up migration) — DROP FUNCTION get_recent_arrivals()
--       after a verify cycle (1 deploy + Jon eyeballs /new).
--
-- Two-step gives reversibility on the function drop without coupling
-- it to the code deploy.
--
-- ─── Decision rationale (architecture-v1.md decision register row #76 amended) ───
--
-- Q2 lock 2026-06-02 (/brand-manager session 2026-06-02 §Q2; canon at
-- branding-guide.md §"Vendor-side sale markdown state-marker" — "Lead-
-- event precedence + Price-field independence" addendum) adds a
-- precedence rule: when multiple event-types fire on the same listing
-- within the observation window, price-dropped > back-in-stock > just-
-- listed wins. Only canon-bearing compound is back-in-stock + price-
-- dropped (OOS → came back lower); other compounds are structurally
-- impossible or precedence-resolved.
--
-- Implication for B-1: the prior get_listing_drop_context() shape was
-- price-drops-only. /new's existing two-arm UNION (migration 0007 +
-- 0027 widen) doesn't surface price-dropped events even though cross-
-- surface medal canon (Q-3 2026-05-18) puts the medal on /new.
-- Generalizing the function to lead-event-precedence-aware lets one SQL
-- surface answer:
--
--   /new           → get_listing_lead_event(NULL, 24, NULL)
--                    fleet-wide, any lead event, LIMIT 100
--   homepage strip → get_listing_lead_event(NULL, 24, NULL)
--                    same; /lead-frontend B-4 wires
--   cross-surface  → get_listing_lead_event(ARRAY[...], 24,
--                    medal callers   ARRAY['price-dropped'])
--                    IN-list, medal-event-only, LIMIT 100
--   /deals         → get_recent_price_drops() — stays separate
--                    (event-monotype, multi-event-per-listing semantic
--                    preserved; today a listing that drops twice in 24h
--                    shows twice on /deals; that semantic doesn't fit
--                    lead-event-per-listing collapse).
--
-- ─── INV-05 binding scope — arm-scoped, not whole-function ───
--
-- INV-05 obligation #4 (medal aggregation scope filter) fires on the
-- price-dropped arm only inside get_listing_lead_event(). just-listed
-- and back-in-stock are auction-orthogonal — auctions legitimately
-- just-list (ReefnBid catalog scrape surfaces new auctions) and back-
-- in-stock (auction relist after no-bid close). The directive binding:
--
--   price-dropped arm:  WHERE vl.auction_end_time IS NULL (INV-05 #4)
--   back-in-stock arm:  no INV-05 predicate
--   just-listed arm:    no INV-05 predicate
--
-- INV-05 #4 also fires on get_recent_price_drops() (DROP + CREATE
-- below) — same predicate, monotype-function variant.
--
-- ─── back-in-stock OOS-duration seam (constant 24h per Q-NEW-D 2026-06-02) ───
--
-- The back_in_stock arm uses a LAG-based OOS-duration threshold:
-- (e.observed_at - e.prior_observed_at) >= interval '24 hours'. The
-- semantic question this answers is "was the listing meaningfully gone
-- before coming back" — i.e., a brief OOS dip doesn't count as a real
-- restock event. Constant 24h NOT scaled with window_hours per Q-NEW-D
-- 2026-06-02 — the seam is a semantic threshold on OOS-duration, not
-- relative to the query window. Window-scaling would strip legitimate
-- restock events at wider queries (a 7-day-window caller asking for
-- back-in-stock events with a 7-day OOS-duration seam would miss every
-- real restock that had <7d of OOS).
--
-- This supersedes migration 0007's vl.first_seen_at <= now() - 24h
-- predicate. Migration 0007's seam was about "listing has established
-- presence" (protecting against brand-new listings surfacing as
-- back-in-stock); Q-NEW-D's OOS-duration semantic implies the same
-- protection (a 25h-old listing can only restock if it was OOS for
-- >= 24h of those 25h — so first_seen_at >= 24h follows from OOS-
-- duration >= 24h). One predicate, cleaner semantic.
--
-- ─── Idempotency + apply path ───
--
-- get_listing_lead_event is CREATE FUNCTION (new). get_recent_price_drops
-- is DROP + CREATE because return-type widen rejects CREATE OR REPLACE.
-- get_listing_drop_context is DROP FUNCTION (orphan retirement).
-- Apply via scripts/apply_migration_0028.py (mirror
-- apply_migration_0027.py shape — scrapers.common.db.get_conn +
-- cursor.execute against NEON_DATABASE_URL per architecture-v1.md
-- decision #65 / CTK-061).

-- ─── 0027 orphan retirement ───
DROP FUNCTION IF EXISTS get_listing_drop_context(bigint[], int);


-- ─── get_listing_lead_event — three-arm UNION + precedence ranking ───
CREATE FUNCTION get_listing_lead_event(
  listing_ids bigint[] DEFAULT NULL,
  window_hours int DEFAULT 24,
  event_filter text[] DEFAULT NULL
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
  LIMIT 100;
$$;

GRANT EXECUTE ON FUNCTION get_listing_lead_event(bigint[], int, text[]) TO service_role, authenticated, anon;


-- ─── get_recent_price_drops — add compare_at_price + INV-05 #4 ───
--
-- /deals stays on this function (event-monotype, multi-event-per-listing
-- semantic preserved — today a listing dropping twice in 24h shows twice
-- on /deals). Body matches CTK-099 migration 0026 verbatim PLUS:
--   - vl.compare_at_price added to the RETURNS TABLE + projection
--     (CTK-109 /deals half; closes hardcoded compareAtPrice: null at
--     lib/queries/listings.ts:406)
--   - AND vl.auction_end_time IS NULL added to outer WHERE (INV-05 #4;
--     closes the predicate 0026 explicitly punted to CTK-047 territory)
-- Return-type widen (compare_at_price added) forces DROP + CREATE.

DROP FUNCTION IF EXISTS get_recent_price_drops();

CREATE FUNCTION get_recent_price_drops()
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
    vl.id, vl.vendor_id, vl.raw_title, vl.current_price, vl.compare_at_price, vl.in_stock,
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
    AND vl.auction_end_time IS NULL
  ORDER BY e.observed_at DESC
  LIMIT 100;
$$;

GRANT EXECUTE ON FUNCTION get_recent_price_drops() TO service_role, authenticated, anon;
