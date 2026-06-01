ALTER TABLE vendor_listings
  ADD COLUMN compare_at_price numeric(10,2);

COMMENT ON COLUMN vendor_listings.compare_at_price IS
  'Vendor-set markdown reference price (the "was" value in a sale render). NULL = no markdown OR markdown invalid (compare_at_price <= current_price nulled at parse per L2). Render predicate: compare_at_price > current_price AND auction_end_time IS NULL (auction_end_time landing in CTK-007). NEVER enters price_history — CTK-047 medal scope structurally clean by construction. Decision #75 (CTK-100 — lands at /architect close-window fold).';
