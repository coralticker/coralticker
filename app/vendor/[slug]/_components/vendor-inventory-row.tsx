// /vendor/[slug] is an inventory-reconciliation surface — getVendorInventory()
// passes in_stock through without filtering (except via the optional IN STOCK
// ONLY user toggle). Inventory rows here can carry namedCoralId === null (no
// match against the seed list) — the Coral field falls back to rawTitle and the
// caveat suppresses entirely; that branch never fires at <VendorAvailabilityRow>
// because /coral/[slug]'s query filters to named_coral_id != null.
//
// Auction listings carry currentPrice === null per project_auctions_in_scope.md
// — rendered as "price on request" via formatPrice() below.

import Image from 'next/image';
import { CaveatLabel } from '@/components/ui/caveat-label';
import { DataRow, type DataRowField } from '@/components/ui/data-row';
import { OutOfStockMarker } from '@/components/ui/out-of-stock-marker';
import type { Listing } from '@/lib/queries/listings';

interface VendorInventoryRowProps {
  listing: Listing;
}

function formatPrice(value: number | null): string {
  if (value === null) return 'price on request';
  return `$${value.toFixed(2)}`;
}

function shouldCaveat(listing: Listing): boolean {
  if (listing.namedCoralCanonicalName === null) return false;
  const c = listing.matchConfidence;
  return c === 'fuzzy' || c === 'manual' || c === null;
}

export function VendorInventoryRow({ listing }: VendorInventoryRowProps) {
  const coralName = listing.namedCoralCanonicalName ?? listing.rawTitle;
  const altText = `${listing.vendorDisplayName} listing of ${coralName}`;
  const isOutOfStock = !listing.inStock;

  const priceFormatted = formatPrice(listing.currentPrice);
  const fields: DataRowField[] = [
    { label: 'Coral', value: coralName },
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
      className="block py-6 border-b border-ink/20 hover:bg-ink/[0.02]"
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
