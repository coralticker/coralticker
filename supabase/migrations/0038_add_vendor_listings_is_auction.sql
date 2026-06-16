-- CTK-042 acute auction-leak gate — Tier 1B.
--
-- Adds the persisted is_auction discriminator on vendor_listings. The
-- canonical auction-state discriminator at decision #70 is
-- auction_end_time IS NOT NULL; that predicate cannot fire on Shopify
-- variant-pseudo-auctions (WWC/POTO/Vivid) — they carry no extractable
-- end-time (CTK-160 root cause: _is_auction detects by tag, not by a
-- timestamp; 0 of 6,872 in_stock rows carry auction_end_time fleet-wide).
-- is_auction is the parallel discriminator that fires on tag-detected
-- auctions; ratified /lead-architect 2026-06-16 as the #70 + INV-05
-- amendment (a deliberate move off "no separate boolean flag" — the
-- end-time-less case #70 did not anticipate).
--
-- Why it leaks: the CTK-160 auction-keep override re-admitted these rows
-- into the cohort lifecycle, so they now surface as just-listed /
-- back-in-stock lead events on the launch email digest (price-on-request,
-- in_stock=true, no end-time). is_auction lets the reader gate them off
-- WITHOUT a false-positive on legitimately null-priced fixed-price rows
-- (JF event-drops, TSA cut-to-order) — the conflation #70 warned against.
--
-- NOT NULL DEFAULT false: every existing row reads fixed-price until the
-- CTK-042 backfill (scrapers/tools/ctk042_is_auction_backfill.py) sets
-- true on the live _is_auction set. New rows get the correct value at
-- parse-time (parse_shopify._normalize_product -> diff.py UPSERT path).
-- APPLY ORDER IS LOAD-BEARING: this column-add, THEN the backfill, THEN
-- 0039's reader gate — gating before the backfill excludes nothing
-- (every row still defaults false).
--
-- Idempotent: ADD COLUMN IF NOT EXISTS. Apply via
-- scripts/apply_migration_0038.py (0033 script shape).

ALTER TABLE vendor_listings
  ADD COLUMN IF NOT EXISTS is_auction boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN vendor_listings.is_auction IS
  'CTK-042 auction discriminator for end-time-less Shopify variant-pseudo-auctions (WWC/POTO/Vivid). true = tag-detected auction (_is_auction at parse-time). Complements the auction_end_time IS NOT NULL discriminator (decision #70) for real-end-time auctions (ReefnBid/CTK-007); the two are independent auction signals. Reader-gate: get_listing_lead_event (all three arms) + getVendorInventory exclude is_auction=true from in-stock / lead-event surfaces. The render-gate (auction_end_time IS NOT NULL, INV-05 #3) is the deferred CTK-042 distinct-render tail. Default false; backfilled true on the live auction set 2026-06-16.';
