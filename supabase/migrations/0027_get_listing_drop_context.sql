-- CTK-047 B-1 + CTK-109 — generalized price-drop RPC + /new + /deals
-- vendor-markdown render parity, single migration.
--
-- Two CREATE statements ship here:
--
--   1. NEW: get_listing_drop_context(listing_ids bigint[], window_hours int)
--      Single SQL surface for both fleet-wide medal aggregation (today's
--      /deals shape) and per-listing drop context for cross-surface
--      rendering (CTK-047 B-3 callers on /, /new, /coral/[slug],
--      /vendor/[slug]). Generalizes get_recent_price_drops() (migration
--      0026); old function left in place untouched — CTK-109 frontend
--      mapper swap to the new function makes 0026's get_recent_price_drops()
--      unused at v1, future cleanup CTK drops it once we've verified no
--      remaining callers (no rework of 0026 needed per /architect bundled-
--      plan-draft directive 2026-06-02).
--
--   2. UPDATED: get_recent_arrivals() — adds vl.compare_at_price to the
--      projection (CTK-109 /new half). Signature change forces DROP +
--      CREATE (CREATE OR REPLACE rejects return-type widen per Postgres
--      docs). GRANT re-asserted post-CREATE.
--
-- ─── Decision rationale (architecture-v1.md decision register rows #76, #77) ───
--
-- B-1 (a) — generalize the existing RPC, not a parallel function.
-- get_recent_price_drops() answered fleet-wide-LIMIT-100 only. CTK-047
-- cross-surface medal needs per-listing drop context for the 4 non-/deals
-- surfaces. Two paths considered: (i) shared TS query helper over plain
-- JOINs (CTK-047 plan §B-1 (a) lean) or (ii) generalized RPC.
-- /lead-architect ruling 2026-06-02: generalized RPC. RPC keeps the LAG
-- partition + window logic in one SQL surface (versus replicating it in
-- TS at the helper layer); behavior matrix on NULL args preserves /deals
-- byte-for-byte today. The same function answers both shapes.
--
-- Behavior matrix:
--   listing_ids IS NULL → fleet-wide LIMIT 100; matches today's
--     get_recent_price_drops() bit-for-bit (LAG-window + in_stock predicate
--     + CTK-099's in_stock=true + CTK-099's order/limit). CTK-109's /deals
--     consumer calls with NULL args; gets the same row set today's RPC
--     returns, plus compare_at_price in the projection.
--   listing_ids = ARRAY[...] → drop context for the listings in the array.
--     Same WHERE shape; just adds the ANY() filter. Cross-surface medal
--     callers pass IN-list (e.g., the listing_ids on the rendered page),
--     LEFT JOIN the result back to their primary query.
--   window_hours parameterized (default 24): /deals stays 24h; future
--     callers could pass 168 for 7-day window without a second function.
--
-- INV-05 obligation #4 first-enforced (coordination-invariants.md §INV-05
-- obligation #4, tracking-checklist row 5). The migration 0026
-- get_recent_price_drops() explicitly punted on the auction_end_time
-- predicate (0026 header comment L20-27); CTK-099 scope-guarded it to
-- CTK-047 territory. Folding the predicate into the same function rewrite
-- here lands all three load-bearing edits in one body:
--   - WHERE vl.auction_end_time IS NULL — closes INV-05 #4 (bid-decrement
--     on closing auction must not surface as a price-drop medal). Open-
--     auction rows are not v1 catalog surface today (no auction-bearing
--     vendor live; first lands at CTK-007 ReefnBid), but the predicate
--     locks the shape at first call site so it cannot drift.
--   - listing_ids filter (B-1 generalization).
--   - compare_at_price in projection (CTK-109's /deals half).
--
-- B-2 (a) — align /coral/[slug] revalidate 1800 → 300 in the consumer
-- (not in this migration). Documented at architecture-v1.md decision
-- register row #77; landed at app/coral/[slug]/page.tsx:15 in the /lead-
-- frontend implementation lane.
--
-- ─── Idempotency + apply path ───
--
-- get_listing_drop_context is CREATE OR REPLACE (new function; idempotent
-- by signature match). get_recent_arrivals is DROP + CREATE because
-- RETURNS TABLE widening (added compare_at_price column) is a return-type
-- change that CREATE OR REPLACE rejects per Postgres docs.
--
-- Apply via the canonical scrapers.common.db.get_conn path per row #65 /
-- CTK-061 amendment (see scripts/apply_migration_0026.py for the script
-- shape sibling CTK-099 used). Migration is forward-safe additive on
-- functions + one column only; no table writes, no backfill. Effect on
-- first call post-apply.
--
-- ─── Supersede note (added 2026-06-02 at Q2 brand-canon amendment) ───
-- get_listing_drop_context() is superseded by migration 0028's
-- get_listing_lead_event() — Q2 lead-event precedence rule (price-dropped
-- > back-in-stock > just-listed; /brand-manager session 2026-06-02 §Q2)
-- required reshaping the function from price-drops-only to three-arm
-- precedence-aware. 0028 DROPs get_listing_drop_context as an orphan
-- (zero production callers — /backend-engineer Session 2 verified the
-- function shape on apply but no consumer migrated before the Q2
-- amendment landed); 0028 also DROP+CREATEs get_recent_price_drops to
-- adopt the compare_at_price + INV-05 predicate inline (so /deals stays
-- on get_recent_price_drops, event-monotype). 0027's ALTER TABLE
-- auction_end_time column-add + get_recent_arrivals widen + GRANTs
-- remain applied state — apply-immutability discipline preserves this
-- file as historical record; 0028 supersedes per CTK-099 → CTK-100
-- supersede pattern. get_recent_arrivals widen stays live in this
-- migration's applied state and continues serving /new until the PR
-- that lands 0028 + /new code switch ships together; 0029 follow-up
-- migration drops get_recent_arrivals after a verify cycle.
--
-- ─── Path-1 carve-out (added 2026-06-02 at /backend-engineer apply ratify) ───
-- ALTER TABLE vendor_listings ADD COLUMN auction_end_time prepended. First
-- apply attempt 2026-06-02 errored UndefinedColumn — the predicate at L154
-- (vl.auction_end_time IS NULL) is INV-05 #4 first-enforce, but no prior
-- migration ever created the column (CTK-100 0025 L5 punted column-add to
-- CTK-007 ReefnBid; CTK-007 hasn't shipped). Jon-ratified path: column
-- materializes here at the reader-site to lock get_listing_drop_context()
-- shape; CTK-007 keeps the writer-side partial index idx_vl_auction_active
-- (OOS-flip lookup) when it ships. Column-existence is INV-05 contract
-- surface; index is CTK-007 mechanism. CTK-007 plan.md L21 amended post-
-- apply by /lead-architect.

ALTER TABLE vendor_listings ADD COLUMN IF NOT EXISTS auction_end_time timestamptz;

COMMENT ON COLUMN vendor_listings.auction_end_time IS
  'Auction end timestamp; NULL = fixed-price row. Canonical auction-state discriminator per INV-05 + architecture-v1 #70. Writer-side population: CTK-007 ReefnBid (Tier 4 trigger-gated) + future auction-bearing vendors. Reader-side: render carve-out (CTK-042) + medal scope filter (CTK-047). First-materialized here at CTK-109 reader-site to lock get_listing_drop_context() shape; column-existence is INV-05 contract surface, not CTK-007 mechanism.';


CREATE OR REPLACE FUNCTION get_listing_drop_context(
  listing_ids bigint[] DEFAULT NULL,
  window_hours int DEFAULT 24
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
  WHERE e.observed_at > now() - (window_hours * interval '1 hour')
    AND e.new_price IS NOT NULL
    AND e.prior_price IS NOT NULL
    AND e.new_price < e.prior_price
    AND vl.current_price IS NOT NULL
    AND vl.in_stock = true
    AND vl.auction_end_time IS NULL
    AND (listing_ids IS NULL OR e.listing_id = ANY(listing_ids))
  ORDER BY e.observed_at DESC
  LIMIT 100;
$$;

GRANT EXECUTE ON FUNCTION get_listing_drop_context(bigint[], int) TO service_role, authenticated, anon;


-- ─── get_recent_arrivals — add compare_at_price (CTK-109 /new half) ───
--
-- Body identical to migration 0007 except for one column added to each
-- CTE projection + the outer SELECT + the RETURNS TABLE. Behavior is
-- unchanged for callers that ignore the new column; CTK-109 mapper at
-- lib/queries/listings.ts:464 reads it through (drops the hardcoded
-- compareAtPrice: null). Preserves migration 0007's UNION two-arm CTE
-- (new_listings + back_in_stock), the back_in_stock dedup-seam predicate
-- vl.first_seen_at <= now() - 24h, and the GRANT.

DROP FUNCTION IF EXISTS get_recent_arrivals();

CREATE FUNCTION get_recent_arrivals()
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
      vl.id, vl.vendor_id, vl.raw_title, vl.current_price, vl.compare_at_price, vl.in_stock,
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
      vl.id, vl.vendor_id, vl.raw_title, vl.current_price, vl.compare_at_price, vl.in_stock,
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
    e.id, e.vendor_id, e.raw_title, e.current_price, e.compare_at_price, e.in_stock,
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

GRANT EXECUTE ON FUNCTION get_recent_arrivals() TO service_role, authenticated, anon;
