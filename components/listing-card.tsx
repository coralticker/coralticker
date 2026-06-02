// Vendor surfaces inline in the lead on every variant via parallel `at {vendor}.`
// grammar per branding-guide.md §"Lead + row composition" — "Vendor attribution
// across lead variants" (CTK-047 Q1 lock 2026-06-02). One rule across all three
// event types; Ref omitted from data row per "Ref. field-presence by composition"
// (same lock).

import { type DataRowField } from '@/components/ui/data-row';
import { ListingRowFrame } from '@/components/ui/listing-row-frame';
import { resolveOriginVendor } from '@/lib/format/origin-vendor';
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

function buildFields(props: ListingCardProps, isOutOfStock: boolean): DataRowField[] {
  const { listing, event } = props;
  const fields: DataRowField[] = [];

  // Event-driven price-drop-new render takes precedence over the
  // invalidated-render when both could apply; the OUT OF STOCK label above
  // the lead carries the row-state declaration independently. Vendor-set
  // markdown (CTK-100 vendor-markdown value-kind) ranks below OOS per L5
  // OOS precedence and above bare-price; predicate guards auction rows
  // (currentPrice === null per project_auctions_in_scope.md L4 parse-side)
  // and folds F7 (≥5% threshold) inline.
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
  } else if (
    listing.compareAtPrice !== null &&
    listing.currentPrice !== null &&
    listing.compareAtPrice >= listing.currentPrice * 1.05
  ) {
    fields.push({
      label: 'Price',
      value: {
        kind: 'vendor-markdown',
        oldValue: formatPrice(listing.compareAtPrice),
        newValue: formatPrice(listing.currentPrice),
      },
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

  // Lineage. field carries origin-only post-CTK-092 (year_introduced dropped
  // per Q-040-11 hold-position path-a). Sentinel suppression — community/
  // canonical → field omitted entirely; <DataRow>'s em-dash interleaving
  // skips the slot automatically. Truthy guards rule out null AND empty-
  // string drift in one boundary.
  if (listing.namedCoralCanonicalName && listing.namedCoralOriginVendor) {
    const originRender = resolveOriginVendor(listing.namedCoralOriginVendor);
    if (!('suppress' in originRender && originRender.suppress)) {
      fields.push({ label: 'Lineage', value: originRender.display });
    }
  }

  return fields;
}

function leadVerb(props: ListingCardProps): string {
  if (props.event === 'just-listed') return 'listed at';
  if (props.event === 'back-in-stock') return 'back in stock at';
  return 'price dropped at';
}

export function ListingCard(props: ListingCardProps) {
  const { listing, matchIndicator } = props;
  const isOutOfStock = !listing.inStock;
  const coralName = listing.namedCoralCanonicalName ?? listing.rawTitle;
  const fields = buildFields(props, isOutOfStock);

  return (
    <ListingRowFrame
      listing={listing}
      fields={fields}
      matchIndicator={matchIndicator}
      leadSlot={
        <p className="text-base leading-snug">
          <strong className="font-bold">{coralName}</strong>{' '}
          <span className="font-normal">{leadVerb(props)}</span>{' '}
          <span>{listing.vendorDisplayName}</span>.
        </p>
      }
    />
  );
}
