import type { ReactNode } from 'react';
import { DataRow, type DataRowField } from '@/components/ui/data-row';
import { OutOfStockMarker } from '@/components/ui/out-of-stock-marker';
import { ThumbSlot } from '@/components/ui/thumb-slot';
import type { Listing } from '@/lib/queries/listings';

interface ListingRowFrameProps {
  listing: Listing;
  fields: DataRowField[];
  /**
   * Optional lead sentence rendered above the data row.
   * Content boundary per branding-guide §"Lead + row composition":
   * single sentence following `**Coral name** [event] vendor.` template.
   * NOT for chrome labels, multi-sentence narrative, or hype-register copy.
   */
  leadSlot?: ReactNode;
  /**
   * Phase 4 wishlist-match reserved prop. No v1 caller passes this; surface
   * activates at Phase 4 paid-tier UI.
   */
  matchIndicator?: boolean;
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
      className="block py-6 border-b border-line hover:bg-wash"
    >
      <div className="flex gap-4">
        <ThumbSlot src={listing.imageUrl} alt={listing.imageUrl ? deriveAltText(listing) : ''} />
        <div className="flex-1 min-w-0">
          {/* OOS render branch is a composition-parity backstop. Feed surfaces
              (/new, /deals) filter in_stock=true at the query layer; this branch
              only fires there if a filter leaks. Inventory surfaces (/coral/[slug],
              /vendor/[slug]) live-render OOS rows by design. */}
          {isOutOfStock ? <OutOfStockMarker /> : null}
          {leadSlot}
          {leadSlot ? <div className="mt-2">{dataRow}</div> : dataRow}
        </div>
      </div>
    </a>
  );
}
