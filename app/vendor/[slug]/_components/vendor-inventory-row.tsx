// /vendor/[slug] is an inventory-reconciliation surface — getVendorInventory()
// passes in_stock through without filtering (except via the optional IN STOCK
// ONLY user toggle). Inventory rows here can carry namedCoralId === null (no
// match against the seed list) — the Coral field falls back to rawTitle and the
// caveat suppresses entirely; that branch never fires at <VendorAvailabilityRow>
// because /coral/[slug]'s query filters to named_coral_id != null.
//
// Auction listings carry currentPrice === null per project_auctions_in_scope.md
// — rendered as "price on request" via formatPrice() below.

import { type DataRowField, type DataRowFieldValue } from '@/components/ui/data-row';
import { ListingRowFrame } from '@/components/ui/listing-row-frame';
import type { Listing } from '@/lib/queries/listings';

interface VendorInventoryRowProps {
  listing: Listing;
}

function formatPrice(value: number | null): string {
  if (value === null) return 'price on request';
  return `$${value.toFixed(2)}`;
}

export function VendorInventoryRow({ listing }: VendorInventoryRowProps) {
  const coralName = listing.namedCoralCanonicalName ?? listing.rawTitle;
  const isOutOfStock = !listing.inStock;
  const priceFormatted = formatPrice(listing.currentPrice);

  // OOS > vendor-markdown > bare per CTK-100 L5 OOS precedence + Wave-3
  // Path A extension. Predicate verbatim across <ListingCard>,
  // <VendorInventoryRow>, <VendorAvailabilityRow>; currentPrice !== null
  // guards auction rows.
  let priceValue: DataRowFieldValue;
  if (isOutOfStock) {
    priceValue = { kind: 'invalidated', value: priceFormatted };
  } else if (
    listing.compareAtPrice !== null &&
    listing.currentPrice !== null &&
    listing.compareAtPrice >= listing.currentPrice * 1.05
  ) {
    priceValue = {
      kind: 'vendor-markdown',
      oldValue: formatPrice(listing.compareAtPrice),
      newValue: priceFormatted,
    };
  } else {
    priceValue = priceFormatted;
  }

  const fields: DataRowField[] = [
    { label: 'Coral', value: coralName },
    { label: 'Price', value: priceValue },
    {
      label: 'Listed',
      value: { kind: 'relative-time', timestamp: listing.firstSeenAt },
    },
  ];

  return <ListingRowFrame listing={listing} fields={fields} />;
}
