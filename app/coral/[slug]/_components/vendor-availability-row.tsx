// /coral/[slug] is an inventory-reconciliation surface — getCoralAvailability()
// passes in_stock through without filtering, so rows can be currently OOS but
// still tied to this coral within the 7-day last_seen_at window.

import { type DataRowField } from '@/components/ui/data-row';
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

  const fields: DataRowField[] = [
    { label: 'Vendor', value: listing.vendorDisplayName },
    {
      label: 'Price',
      value: isOutOfStock
        ? { kind: 'invalidated', value: priceFormatted }
        : priceFormatted,
    },
    {
      label: 'Listed',
      value: { kind: 'relative-time', timestamp: listing.firstSeenAt },
    },
  ];

  return <ListingRowFrame listing={listing} fields={fields} />;
}
