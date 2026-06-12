// Shared Price-field value-builder for the standing-listing row consumers
// (<ListingCard>, <VendorInventoryRow>, <VendorAvailabilityRow>). Consolidates
// the OOS > price-drop-new > vendor-markdown > bare decision tree that was wired
// verbatim into all three sites (predicate-drift risk on the next change).
//
// Pure value-builder, NOT a JSX component: it returns a DataRowFieldValue and
// the strikethrough/forest-bold DOM stays at <RenderValue> (shared formatValue()
// string + shared <del> DOM). The builder takes `listing` alone; the three trees
// are byte-identical (no consumer carries a Price-side event — the lead-verb
// promotion in <ListingCard>.deriveLeadEvent is a separate concern and stays
// there).

import type { DataRowFieldValue } from '@/components/ui/data-row';
import type { Listing } from '@/lib/queries/listings';

// Auction rows carry currentPrice === null (parse-side null-out) →
// "price on request".
function formatPrice(value: number | null): string {
  if (value === null) return 'price on request';
  return `$${value.toFixed(2)}`;
}

// Precedence: OOS (invalidated) > price-drop-new > vendor-markdown > bare.
//
// Vendor-markdown predicate is the float-imprecision-corrected form: the
// straightforward `compareAtPrice >= currentPrice * 1.05` silently misses ~29%
// of integer-dollar clean 5% markdowns because IEEE754 1.05 + the multiply
// nudges the threshold above the true mark (e.g. 3 * 1.05 = 3.1500000000000004;
// 3.15 < that). Subtract-then-compare with a 1e-9 epsilon preserves the ≥5%
// semantic.
//
// The `currentPrice > 0` guard folds into this same branch: a phantom
// currentPrice = 0 with a positive compareAtPrice would otherwise render a bogus
// markdown. With the guard it falls through to bare ($0.00) — a no-op on real
// data (vendors don't post 0; the auction null-out yields null, not 0), but the
// bug-shape is resolved by construction. The `!== null` checks stay for TS
// narrowing on the arithmetic.
export function buildPriceValue(listing: Listing): DataRowFieldValue {
  if (!listing.inStock) {
    return { kind: 'invalidated', value: formatPrice(listing.currentPrice) };
  }
  if (listing.priorPrice !== null && listing.currentPrice !== null) {
    return {
      kind: 'price-drop-new',
      oldValue: formatPrice(listing.priorPrice),
      newValue: formatPrice(listing.currentPrice),
    };
  }
  if (
    listing.compareAtPrice !== null &&
    listing.currentPrice !== null &&
    listing.currentPrice > 0 &&
    (listing.compareAtPrice - listing.currentPrice) >=
      listing.currentPrice * 0.05 - 1e-9
  ) {
    return {
      kind: 'vendor-markdown',
      oldValue: formatPrice(listing.compareAtPrice),
      newValue: formatPrice(listing.currentPrice),
    };
  }
  return formatPrice(listing.currentPrice);
}
