// /coral/[slug] is an inventory-reconciliation surface — getCoralAvailability()
// passes in_stock through without filtering, so rows can be currently OOS but
// still tied to this coral within the 7-day last_seen_at window.

import Image from 'next/image';
import { CaveatLabel } from '@/components/ui/caveat-label';
import { DataRow, type DataRowField } from '@/components/ui/data-row';
import { OutOfStockMarker } from '@/components/ui/out-of-stock-marker';
import type { Listing } from '@/lib/queries/listings';

interface VendorAvailabilityRowProps {
  listing: Listing;
}

function formatPrice(value: number | null): string {
  if (value === null) return 'price on request';
  return `$${value.toFixed(2)}`;
}

function shouldCaveat(listing: Listing): boolean {
  const c = listing.matchConfidence;
  return c === 'fuzzy' || c === 'manual' || c === null;
}

export function VendorAvailabilityRow({ listing }: VendorAvailabilityRowProps) {
  const coralName = listing.namedCoralCanonicalName ?? listing.rawTitle;
  const altText = `${listing.vendorDisplayName} listing of ${coralName}`;
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

  return (
    <a
      href={listing.productUrl}
      target="_blank"
      rel="noopener noreferrer"
      className="block py-6 border-b border-ink/30 hover:bg-ink/[0.02]"
    >
      <div className="flex gap-4">
        <div className="shrink-0 w-24 h-24 bg-ink/5" aria-hidden={!listing.imageUrl}>
          {listing.imageUrl ? (
            <Image
              src={listing.imageUrl}
              alt={altText}
              width={96}
              height={96}
              sizes="96px"
              unoptimized
              className="w-24 h-24 object-cover"
            />
          ) : null}
        </div>
        <div className="flex-1 min-w-0">
          {isOutOfStock ? <OutOfStockMarker /> : null}
          <DataRow fields={fields} />
          {shouldCaveat(listing) ? (
            <div className="mt-1">
              <CaveatLabel kind="match-name-based" />
            </div>
          ) : null}
        </div>
      </div>
    </a>
  );
}
