// /coral/[slug] is an inventory-reconciliation surface — getCoralAvailability()
// passes in_stock through without filtering, so rows can be currently OOS but
// still tied to this coral within the 7-day last_seen_at window.
//
// Price-drop medal at position 2 in the precedence chain
// (OOS > price-drop-new > vendor-markdown > bare). Listing.priorPrice populated
// via getListingDropContext() LEFT JOIN in getCoralAvailability() — null for
// listings with no CT-observed drop in the 24h window, in which case the chain
// falls through to vendor-markdown / bare.

import { type DataRowField } from '@/components/ui/data-row';
import { ListingRowFrame } from '@/components/ui/listing-row-frame';
import { buildPriceValue } from '@/lib/format/listing-price';
import type { Listing } from '@/lib/queries/listings';

interface VendorAvailabilityRowProps {
  listing: Listing;
}

export function VendorAvailabilityRow({ listing }: VendorAvailabilityRowProps) {
  // OOS > price-drop-new > vendor-markdown > bare via the shared
  // buildPriceValue().
  const fields: DataRowField[] = [
    { label: 'Vendor', value: listing.vendorDisplayName },
    { label: 'Price', value: buildPriceValue(listing) },
    {
      label: 'Listed',
      // eventAt populated by getCoralAvailability's merge for rows with a
      // recent CT-observed drop; falls back to firstSeenAt elsewhere.
      value: {
        kind: 'relative-time',
        timestamp: listing.eventAt ?? listing.firstSeenAt,
      },
    },
  ];

  return <ListingRowFrame listing={listing} fields={fields} />;
}
