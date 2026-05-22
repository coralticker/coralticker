// Price-dropped lead sentence omits the vendor by design — the new price is
// the headline; vendor is recoverable via image alt, Ref field, and card
// grouping. just-listed / back-in-stock leads keep the vendor inline.
//
// OOS render branch is a cross-surface composition-parity backstop: feed
// surfaces (`/`, `/new`, `/deals`) filter `in_stock = true` at the query
// layer, so the branch only fires if a filter leaks. /coral/[slug] and
// /vendor/[slug] live OOS rendering happens at <VendorAvailabilityRow> +
// <VendorInventoryRow>.

import Image from 'next/image';
import { CaveatLabel } from '@/components/ui/caveat-label';
import { DataRow, type DataRowField } from '@/components/ui/data-row';
import { OutOfStockMarker } from '@/components/ui/out-of-stock-marker';
import { formatLineage } from '@/lib/format/lineage';
import type { Listing } from '@/lib/queries/listings';

type ListingCardProps =
  | { listing: Listing; event: 'just-listed'; matchIndicator?: boolean }
  | { listing: Listing; event: 'back-in-stock'; observedAt: string; matchIndicator?: boolean }
  | {
      listing: Listing;
      event: 'price-dropped';
      priorPrice: number;
      observedAt: string;
      matchIndicator?: boolean;
    };

function formatPrice(value: number | null): string {
  if (value === null) return 'price on request';
  return `$${value.toFixed(2)}`;
}

function derivedRef(productUrl: string): string {
  try {
    const u = new URL(productUrl);
    const tail = u.pathname.split('/').filter(Boolean).pop() ?? '';
    return tail || u.hostname;
  } catch {
    return productUrl;
  }
}

function shouldCaveat(listing: Listing): boolean {
  if (listing.namedCoralCanonicalName === null) return false;
  const c = listing.matchConfidence;
  return c === 'fuzzy' || c === 'manual' || c === null;
}

function buildFields(props: ListingCardProps, isOutOfStock: boolean): DataRowField[] {
  const { listing, event } = props;
  const fields: DataRowField[] = [
    { label: 'Ref', value: derivedRef(listing.productUrl) },
  ];

  // Event-driven price-drop-new render takes precedence over the
  // invalidated-render when both could apply; the OUT OF STOCK label above
  // the lead carries the row-state declaration independently.
  if (event === 'price-dropped') {
    fields.push({
      label: 'Price',
      value: {
        kind: 'price-drop-new',
        oldValue: formatPrice(props.priorPrice),
        newValue: formatPrice(listing.currentPrice),
      },
    });
  } else if (isOutOfStock) {
    fields.push({
      label: 'Price',
      value: { kind: 'invalidated', value: formatPrice(listing.currentPrice) },
    });
  } else {
    fields.push({ label: 'Price', value: formatPrice(listing.currentPrice) });
  }

  const listedTimestamp =
    event === 'just-listed' ? listing.firstSeenAt : props.observedAt;
  fields.push({
    label: 'Listed',
    value: { kind: 'relative-time', timestamp: listedTimestamp },
  });

  if (
    listing.namedCoralCanonicalName !== null &&
    (listing.namedCoralOriginVendor !== null ||
      listing.namedCoralYearIntroduced !== null)
  ) {
    const lineage = formatLineage({
      origin_vendor: listing.namedCoralOriginVendor,
      year_introduced: listing.namedCoralYearIntroduced,
    });
    if (lineage.length > 0) {
      fields.push({ label: 'Lineage', value: lineage });
    }
  }

  return fields;
}

function leadVerb(props: ListingCardProps): string {
  if (props.event === 'just-listed') return 'listed at';
  if (props.event === 'back-in-stock') return 'back in stock at';
  return `price dropped — was ${formatPrice(props.priorPrice)}, now ${formatPrice(props.listing.currentPrice)}.`;
}

export function ListingCard(props: ListingCardProps) {
  const { listing, matchIndicator } = props;
  const isOutOfStock = !listing.inStock;
  const coralName = listing.namedCoralCanonicalName ?? listing.rawTitle;
  const altText = listing.namedCoralCanonicalName
    ? `${listing.vendorDisplayName} listing of ${listing.namedCoralCanonicalName}`
    : `${listing.vendorDisplayName} listing — ${listing.rawTitle}`;
  const fields = buildFields(props, isOutOfStock);

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
          {isOutOfStock ? <OutOfStockMarker /> : null}
          <p className="text-base leading-snug">
            <strong className="font-bold">{coralName}</strong>{' '}
            <span className="font-normal">{leadVerb(props)}</span>
            {props.event === 'price-dropped' ? null : (
              <>
                {' '}
                <span>{listing.vendorDisplayName}</span>.
              </>
            )}
          </p>
          <div className="mt-2">
            <DataRow fields={fields} matchIndicator={matchIndicator} />
          </div>
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
