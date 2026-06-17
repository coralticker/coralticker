-- CTK-161 F9 — deterministic ORDER BY tiebreak on get_cross_vendor_carriers().
--
-- Retro /code-review of PR #9 (finding #2, 2026-06-17): the 0043 ORDER BY
-- `(named_coral_id, first_seen_at DESC)` has no unique final tiebreak. When two
-- carriers of the same coral share a first_seen_at (cold-start backfill sets
-- first_seen_at in the past, so identical-timestamp collisions are plausible),
-- the row order is non-deterministic across runs. select_f9_lineage's per-vendor
-- inner pick stable-sorts by event_at and keeps the first row per vendor, so it
-- inherits the SQL order for ties — a different listing (price / product_url) can
-- render for that vendor with no data change, and any F9 golden test is born flaky.
--
-- Fix: add `vl.id DESC` as the final tiebreak — a total order. Mirrors the
-- deterministic-velocity-ordering fold (commit 7af0a79). select_f9_lineage gains
-- a matching `(event_at, id)` sort key (defense-in-depth) so the Python is
-- self-deterministic regardless of source order.
--
-- CREATE OR REPLACE — idempotent, re-runnable, no DROP, no table writes. The only
-- change vs. 0043 is the ORDER BY tail; column shape + WHERE + GRANT unchanged.
-- Apply via the canonical migration path (scrapers.common.db.get_conn against
-- NEON_DATABASE_URL) — separate step; this file is the definition only.

CREATE OR REPLACE FUNCTION get_cross_vendor_carriers()
RETURNS TABLE (
  id bigint,
  vendor_id smallint,
  named_coral_id integer,
  current_price numeric,
  in_stock boolean,
  image_url text,
  product_url text,
  event_at timestamptz,
  vendor_slug text,
  vendor_display_name text,
  named_coral_canonical_name text,
  named_coral_slug text
)
LANGUAGE sql
STABLE
AS $$
  SELECT
    vl.id, vl.vendor_id, vl.named_coral_id, vl.current_price,
    vl.in_stock, vl.image_url, vl.product_url,
    vl.first_seen_at    AS event_at,           -- the 'listed' event time F9 orders on
    v.slug              AS vendor_slug,
    v.display_name      AS vendor_display_name,
    nc.canonical_name   AS named_coral_canonical_name,
    nc.slug             AS named_coral_slug
  FROM vendor_listings vl
  JOIN vendors v ON v.id = vl.vendor_id
  JOIN named_corals nc ON nc.id = vl.named_coral_id
  WHERE vl.named_coral_id IS NOT NULL
    AND vl.in_stock = true
    AND vl.auction_end_time IS NULL            -- INV-05 residual (D-3)
    AND vl.is_auction = false                  -- CTK-042 pseudo-auction availability gate
  ORDER BY vl.named_coral_id, vl.first_seen_at DESC, vl.id DESC;  -- vl.id DESC = total-order tiebreak (#2)
$$;

GRANT EXECUTE ON FUNCTION get_cross_vendor_carriers() TO service_role, authenticated, anon;
