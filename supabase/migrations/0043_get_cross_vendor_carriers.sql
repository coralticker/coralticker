-- CTK-161 F9 lineage-spotlight data layer — get_cross_vendor_carriers().
--
-- The F9 ("lineage spotlight") format is "one named coral, many sellers": the
-- cover names the lineage + how many vendors carry it right now, inner slides
-- render one listing per vendor (rev2 L219-234). This function returns the raw
-- material — every in-stock carrying listing of every named coral — and leaves
-- the SELECTION (which coral to spotlight, the >= 2-vendor gate, per-vendor
-- dedupe, recency order, card-eligibility) to the Python curator
-- content_queries.select_f9_lineage. Same division of labor as the cross_vendor
-- ranking: the SQL surfaces the eligible population, the Python applies the
-- editorial pick (mirrors cross_vendor_cheapest_ids as the reference-spec ranker).
--
-- Sibling to get_cross_vendor_cheapest (migration 0041) — SAME eligible-carrier
-- predicate, but NEVER price-ranked: F9 inners are recency-ordered (event_at),
-- never cheapest-first. So this function does NOT compute min-price / crown rows;
-- it returns all eligible carriers with the 'listed' event time (first_seen_at)
-- the render orders on. The per-coral distinct-vendor count is computed Python-
-- side over these rows (image-blind by construction — no image filter here), so
-- the honest cover count ("at N vendors right now") is the TRUE carrier count,
-- not the deflated card-eligible sample.
--
-- ─── Auction gates (INV-05 residual + CTK-042) ───
--
-- Runs over the full vendor_listings population (not built on get_listing_lead_
-- event), so the auction predicates are re-asserted INDEPENDENTLY:
--   - auction_end_time IS NULL  — INV-05 residual (D-3): no real-end-time auction
--     (ReefnBid / CTK-007) crowned a "carrier."
--   - is_auction = false        — CTK-042 ratified gate (migration 0039,
--     2026-06-16): excludes today's end-time-less Shopify pseudo-auctions, which
--     PASS auction_end_time IS NULL but are availability-deceptive. F9's cover is
--     an availability claim ("carried at N vendors RIGHT NOW") — the exact leak
--     surface CTK-042 closed for the digest. get_cross_vendor_cheapest (0041) is
--     price-guarded against pseudo-auctions (current_price IS NOT NULL nulls them
--     out); F9 keeps price-null carriers as legitimate "price on request" sellers,
--     so it needs the is_auction gate explicitly. (Carriers are NOT price-gated:
--     a non-auction in-stock listing with no price is an honest carrier of the
--     coral — counted in the cover; it simply can't render as an inner card,
--     which the Python card-eligibility filter handles.)
--
-- CREATE OR REPLACE (new function — no prior definition). GRANT EXECUTE re-
-- asserted post-CREATE, same grantee set as 0041. Apply via the canonical
-- migration path (scrapers.common.db.get_conn against NEON_DATABASE_URL,
-- architecture-v1.md decision #65) — separate, Jon-side step; this file is the
-- definition only.

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
  ORDER BY vl.named_coral_id, vl.first_seen_at DESC;
$$;

GRANT EXECUTE ON FUNCTION get_cross_vendor_carriers() TO service_role, authenticated, anon;
