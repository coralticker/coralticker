// §4.1 <VendorAvailabilityRow> — single-view co-located composition
//
// Per site.md §4.1 + Decision K (single-view co-located; inverse first-field
// semantics from /vendor/[slug]'s <VendorInventoryRow>). Renders one vendor's
// current listing for a named coral: thumbnail + <DataRow fields={[Vendor, Price,
// Listed]}> + conditional <CaveatLabel> when match is name-based.
//
// NO event lead. The page H1 carries the coral name; this row is bare data +
// caveat. That structural difference from <ListingCard> earned the co-location.
//
// Alt text derived inside: `${vendorDisplayName} listing of ${namedCoralCanonicalName}`.
// Every row on /coral/[slug] has named_coral_id != null by query filter, so
// canonicalName is always available.
//
// CTK-070: live OOS render branch. /coral/[slug] is an inventory-reconciliation
// surface — getCoralAvailability() passes in_stock through without filtering
// (rows can be currently OOS but still tied to this coral within the 7-day
// last_seen_at window). When listing.inStock === false, render the mono-
// uppercase OUT OF STOCK label in the row state-marker slot (above the row,
// mirrors WISHLIST MATCH prefix shape per branding-guide.md L207) AND
// strikethrough the Price field via {kind: 'invalidated'} per the new L197
// generalized canon. Near-black, NOT forest — preserves the 5-job lock.

import Image from 'next/image';
import { CaveatLabel } from '@/components/ui/caveat-label';
import { DataRow, type DataRowField } from '@/components/ui/data-row';
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
      className="block py-6 border-b border-ink/10 hover:bg-ink/[0.02]"
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
          {isOutOfStock ? (
            <p className="text-xs uppercase tracking-[0.08em] font-mono text-ink mb-1">
              Out of stock
            </p>
          ) : null}
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
