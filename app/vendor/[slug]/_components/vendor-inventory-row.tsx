// /vendor/[slug] is an inventory-reconciliation surface — getVendorInventory()
// passes in_stock through without filtering (except via the optional IN STOCK
// ONLY user toggle). Inventory rows here can carry namedCoralId === null (no
// match against the seed list) — the Coral field falls back to rawTitle and the
// caveat suppresses entirely; that branch never fires at <VendorAvailabilityRow>
// because /coral/[slug]'s query filters to named_coral_id != null.
//
// Auction listings carry currentPrice === null per project_auctions_in_scope.md
// — rendered as "price on request" via the shared buildPriceValue().
//
// CTK-047 B-3 — cross-surface price-drop medal at position 2 in the precedence
// chain (OOS > price-drop-new > vendor-markdown > bare). Predicate verbatim
// across <ListingCard>, <VendorInventoryRow>, <VendorAvailabilityRow> per
// branding-guide L228 OOS precedence + CTK-100 Wave-3 cross-consumer doctrine.
// Listing.priorPrice populated via getListingDropContext() LEFT JOIN in
// getVendorInventory() — null for listings with no CT-observed drop in the
// 24h window, in which case the chain falls through to vendor-markdown / bare.

import { type DataRowField } from '@/components/ui/data-row';
import { ListingRowFrame } from '@/components/ui/listing-row-frame';
import { buildPriceValue } from '@/lib/format/listing-price';
import type { Listing } from '@/lib/queries/listings';

interface VendorInventoryRowProps {
  listing: Listing;
}

export function VendorInventoryRow({ listing }: VendorInventoryRowProps) {
  const coralName = listing.namedCoralCanonicalName ?? listing.rawTitle;

  // OOS > price-drop-new > vendor-markdown > bare via the shared
  // buildPriceValue() — CTK-103 F3 consolidation (predicate verbatim across
  // <ListingCard>, <VendorInventoryRow>, <VendorAvailabilityRow>).
  const fields: DataRowField[] = [
    { label: 'Coral', value: coralName },
    { label: 'Price', value: buildPriceValue(listing) },
    {
      label: 'Listed',
      // CTK-047 close-window: eventAt populated by getVendorInventory's merge
      // for rows with a recent CT-observed drop; falls back to firstSeenAt
      // elsewhere. Matches <ListingCard> fallback chain.
      value: {
        kind: 'relative-time',
        timestamp: listing.eventAt ?? listing.firstSeenAt,
      },
    },
  ];

  return <ListingRowFrame listing={listing} fields={fields} />;
}
