// §4.5 <VendorInventoryRow> — single-view co-located composition
//
// Per site.md §4.5 + Decision K. Structural inversion of <VendorAvailabilityRow>
// (`/coral/[slug]`'s co-located composition): coral-per-row here (vendor is
// fixed by page H1); vendor-per-row at `/coral/[slug]` (coral fixed by H1).
// Different first-field, different field semantics, same brand-discipline
// pattern. Co-location earns its keep on Decision D inclusion bar (single-view).
//
// NO event lead. Page H1 carries the vendor lead; this row is bare data + caveat.
// Same Decision D risk-language fold that drove <ListingCard>'s 5→3 cascade.
//
// Caveat suppression covers an extra case here that does NOT fire at
// <VendorAvailabilityRow>: when `namedCoralId === null` (no match against the
// seed list at all), the caveat suppresses entirely and the Coral field renders
// `rawTitle` literal. /coral/[slug]'s query filters to `named_coral_id != null`,
// so that branch never fires there.
//
// Auction listings carry `currentPrice === null` per project_auctions_in_scope.md
// (2026-05-14) — rendered as "price on request" via formatPrice() below; the
// query layer deliberately does NOT filter `current_price IS NOT NULL` away.

import Image from 'next/image';
import { CaveatLabel } from '@/components/ui/caveat-label';
import { DataRow, type DataRowField } from '@/components/ui/data-row';
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

  const fields: DataRowField[] = [
    { label: 'Coral', value: coralName },
    { label: 'Price', value: formatPrice(listing.currentPrice) },
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
