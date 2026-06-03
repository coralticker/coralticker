// /coral/[slug] is an inventory-reconciliation surface — getCoralAvailability()
// passes in_stock through without filtering, so rows can be currently OOS but
// still tied to this coral within the 7-day last_seen_at window.
//
// CTK-047 B-3 — cross-surface price-drop medal at position 2 in the precedence
// chain (OOS > price-drop-new > vendor-markdown > bare). Predicate verbatim
// across <ListingCard>, <VendorInventoryRow>, <VendorAvailabilityRow> per
// branding-guide L228 OOS precedence + CTK-100 Wave-3 cross-consumer doctrine.
// Listing.priorPrice populated via getListingDropContext() LEFT JOIN in
// getCoralAvailability() — null for listings with no CT-observed drop in the
// 24h window, in which case the chain falls through to vendor-markdown / bare.

import { type DataRowField, type DataRowFieldValue } from '@/components/ui/data-row';
import { ListingRowFrame } from '@/components/ui/listing-row-frame';
import type { Listing } from '@/lib/queries/listings';

interface VendorAvailabilityRowProps {
  listing: Listing;
}

function formatPrice(value: number | null): string {
  if (value === null) return 'price on request';
  return `$${value.toFixed(2)}`;
}

export function VendorAvailabilityRow({ listing }: VendorAvailabilityRowProps) {
  const isOutOfStock = !listing.inStock;
  const priceFormatted = formatPrice(listing.currentPrice);

  // OOS > price-drop-new > vendor-markdown > bare per CTK-047 B-3 + CTK-100
  // L5 OOS precedence. Predicate verbatim across <ListingCard>,
  // <VendorInventoryRow>, <VendorAvailabilityRow>; currentPrice !== null
  // guards auction rows.
  let priceValue: DataRowFieldValue;
  if (isOutOfStock) {
    priceValue = { kind: 'invalidated', value: priceFormatted };
  } else if (
    listing.priorPrice !== null &&
    listing.currentPrice !== null
  ) {
    priceValue = {
      kind: 'price-drop-new',
      oldValue: formatPrice(listing.priorPrice),
      newValue: priceFormatted,
    };
  } else if (
    listing.compareAtPrice !== null &&
    listing.currentPrice !== null &&
    (listing.compareAtPrice - listing.currentPrice) >=
      listing.currentPrice * 0.05 - 1e-9
  ) {
    // Float-imprecision rewrite per /code-review 2026-06-03 — same predicate
    // verbatim as <ListingCard> + <VendorInventoryRow> per CTK-100 Wave-3
    // cross-consumer doctrine.
    priceValue = {
      kind: 'vendor-markdown',
      oldValue: formatPrice(listing.compareAtPrice),
      newValue: priceFormatted,
    };
  } else {
    priceValue = priceFormatted;
  }

  const fields: DataRowField[] = [
    { label: 'Vendor', value: listing.vendorDisplayName },
    { label: 'Price', value: priceValue },
    {
      label: 'Listed',
      // CTK-047 close-window: eventAt populated by getCoralAvailability's
      // merge for rows with a recent CT-observed drop; falls back to
      // firstSeenAt elsewhere. Matches <ListingCard> fallback chain.
      value: {
        kind: 'relative-time',
        timestamp: listing.eventAt ?? listing.firstSeenAt,
      },
    },
  ];

  return <ListingRowFrame listing={listing} fields={fields} />;
}
