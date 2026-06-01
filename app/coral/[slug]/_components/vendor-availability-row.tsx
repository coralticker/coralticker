// /coral/[slug] is an inventory-reconciliation surface — getCoralAvailability()
// passes in_stock through without filtering, so rows can be currently OOS but
// still tied to this coral within the 7-day last_seen_at window.

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
    { label: 'Vendor', value: listing.vendorDisplayName },
    { label: 'Price', value: priceValue },
    {
      label: 'Listed',
      value: { kind: 'relative-time', timestamp: listing.firstSeenAt },
    },
  ];

  return <ListingRowFrame listing={listing} fields={fields} />;
}
