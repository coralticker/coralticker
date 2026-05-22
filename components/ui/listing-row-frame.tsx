import type { ReactNode } from 'react';
import Image from 'next/image';
import { CaveatLabel } from '@/components/ui/caveat-label';
import { DataRow, type DataRowField } from '@/components/ui/data-row';
import { OutOfStockMarker } from '@/components/ui/out-of-stock-marker';
import type { Listing } from '@/lib/queries/listings';

interface ListingRowFrameProps {
  listing: Listing;
  fields: DataRowField[];
  /**
   * Optional lead sentence rendered above the data row.
   * Content boundary per branding-guide.md §"Lead + row composition" (L256-268):
   * single sentence following `**Coral name** [event] vendor.` template.
   * NOT for chrome labels, multi-sentence narrative, or hype-register copy.
   */
  leadSlot?: ReactNode;
  /**
   * Phase 4 wishlist-match reserved prop per CTK-014 site.md L505/521/552/652.
   * No v1 caller passes this; surface activates at Phase 4 paid-tier UI.
   */
  matchIndicator?: boolean;
}

function shouldCaveat(listing: Listing): boolean {
  if (listing.namedCoralCanonicalName === null) return false;
  const c = listing.matchConfidence;
  return c === 'fuzzy' || c === 'manual' || c === null;
}

function deriveAltText(listing: Listing): string {
  if (listing.namedCoralCanonicalName !== null) {
    return `${listing.vendorDisplayName} listing of ${listing.namedCoralCanonicalName}`;
  }
  return `${listing.vendorDisplayName} listing — ${listing.rawTitle}`;
}

export function ListingRowFrame({
  listing,
  fields,
  leadSlot,
  matchIndicator,
}: ListingRowFrameProps) {
  const isOutOfStock = !listing.inStock;
  const dataRow = <DataRow fields={fields} matchIndicator={matchIndicator} />;

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
              alt={deriveAltText(listing)}
              width={96}
              height={96}
              sizes="96px"
              unoptimized
              className="w-24 h-24 object-cover"
            />
          ) : null}
        </div>
        <div className="flex-1 min-w-0">
          {/* OOS render branch is a composition-parity backstop. Feed surfaces
              (/new, /deals) filter in_stock=true at the query layer; this branch
              only fires there if a filter leaks. Inventory surfaces (/coral/[slug],
              /vendor/[slug]) live-render OOS rows by design. */}
          {isOutOfStock ? <OutOfStockMarker /> : null}
          {leadSlot}
          {leadSlot ? <div className="mt-2">{dataRow}</div> : dataRow}
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
