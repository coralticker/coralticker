// lib/format/vendor-count.ts
//
// The one count-rule source of truth for CURRENT-availability vendor counts
// (CTK-187; the shared atom CTK-182's buildMarketLine extraction folds into).
// Both current-availability surfaces — the /coral/[slug] eyebrow and the
// /guides/[slug] market line — derive their vendor count from here so the
// in-stock semantics can't drift between them (the exact divergence the
// vendorN 3-stage-parity bug at CTK-162 /code-review exposed).
//
// Rule: distinct in-stock vendors = COUNT(DISTINCT vendorSlug) over rows where
// inStock === true. The inStock filter is load-bearing and NOT optional: the
// /coral/[slug] ?include-oos=1 toggle puts OOS rows into the listings array, so
// a raw count over all rows would over-report (the Tier-1B "1 VENDOR" beside an
// empty default buy-view defect this ticket fixes). 0 in-stock vendors is a real
// answer — callers render the all-OOS state word, never "0 VENDORS".
//
// NOT the historical count: /coral/[slug]/price-history counts distinct vendors
// with >=1 listing in the window INCLUDING now-OOS carriers (the chart draws
// their past lines). That is a deliberately different rule and does not call here.
export function distinctInStockVendorCount(
  listings: ReadonlyArray<{ inStock: boolean; vendorSlug: string }>,
): number {
  const vendors = new Set<string>();
  for (const listing of listings) {
    if (listing.inStock) vendors.add(listing.vendorSlug);
  }
  return vendors.size;
}
