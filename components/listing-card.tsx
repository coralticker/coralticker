// Lead and Price both derive from listing fields per the precedence chain
// (branding-guide §"Vendor-side sale markdown state-marker" → "Lead promotion
// on strikethrough Price."):
//
//   OOS (invalidated): lead = baseEvent ("listed at" / "back in stock at"),
//     Price = invalidated. OOS does NOT promote the lead per the invalidation
//     semantic — supersedes the promotion semantic.
//   CT-observed price-drop (priorPrice + priceDropObservedAt non-null):
//     lead = "price dropped at", Price = price-drop-new (oldValue = priorPrice).
//   Vendor-markdown ≥5% (compareAtPrice >= currentPrice * 1.05): lead =
//     "price dropped at" (lead promotion), Price = vendor-markdown
//     (oldValue = compareAtPrice).
//   Otherwise: lead = baseEvent, Price = bare current price.
//
// baseEvent prop carries the back-in-stock vs. just-listed hint from the
// caller. The composition overrides with "price dropped at" via the
// derivation rule above; baseEvent only fires for non-price-drop rows.
// /deals + homepage strip pass no baseEvent and accept the 'just-listed'
// default — neither surface distinguishes restock vs. first-listing at the
// lead level (composition reads Price-shape signals from listing fields).

import { type DataRowField } from '@/components/ui/data-row';
import { ListingRowFrame } from '@/components/ui/listing-row-frame';
import { buildPriceValue } from '@/lib/format/listing-price';
import { resolveOriginVendor } from '@/lib/format/origin-vendor';
import type { Listing } from '@/lib/queries/listings';

interface ListingCardProps {
  listing: Listing;
  baseEvent?: 'just-listed' | 'back-in-stock';
  matchIndicator?: boolean;
}

function deriveLeadEvent(
  listing: Listing,
  baseEvent: 'just-listed' | 'back-in-stock' = 'just-listed',
): { verb: string; isPriceDropped: boolean } {
  // OOS does NOT promote (invalidated semantic).
  if (!listing.inStock) {
    return {
      verb: baseEvent === 'just-listed' ? 'listed at' : 'back in stock at',
      isPriceDropped: false,
    };
  }
  // CT-observed price-drop wins over vendor-markdown promotion when both
  // could apply (the listing actually moved within the 24h window).
  if (listing.priorPrice !== null && listing.priceDropObservedAt !== null) {
    return { verb: 'price dropped at', isPriceDropped: true };
  }
  // Vendor-markdown strikethrough promotes the lead.
  // The straightforward `compareAtPrice >= currentPrice * 1.05` form silently
  // misses ~29% of integer-dollar clean 5% markdowns because IEEE754
  // representation of 1.05 + the multiply nudges the threshold above the
  // true mark (e.g., 3 * 1.05 = 3.1500000000000004; 3.15 < 3.1500000000000004).
  // Subtract-then-compare with a 1e-9 epsilon preserves the semantic.
  if (
    listing.compareAtPrice !== null &&
    listing.currentPrice !== null &&
    (listing.compareAtPrice - listing.currentPrice) >=
      listing.currentPrice * 0.05 - 1e-9
  ) {
    return { verb: 'price dropped at', isPriceDropped: true };
  }
  return {
    verb: baseEvent === 'just-listed' ? 'listed at' : 'back in stock at',
    isPriceDropped: false,
  };
}

function buildFields(listing: Listing): DataRowField[] {
  const fields: DataRowField[] = [];

  // Price precedence chain (OOS > price-drop-new > vendor-markdown > bare)
  // lives in the shared buildPriceValue(). The lead-promotion logic
  // (deriveLeadEvent above) changes the LEAD derivation only, not the Price.
  fields.push({ label: 'Price', value: buildPriceValue(listing) });

  fields.push({
    label: 'Listed',
    value: {
      kind: 'relative-time',
      timestamp: listing.eventAt ?? listing.firstSeenAt,
    },
  });

  // Lineage. field carries origin-only. Sentinel suppression — community/
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

export function ListingCard({ listing, baseEvent, matchIndicator }: ListingCardProps) {
  const coralName = listing.namedCoralCanonicalName ?? listing.rawTitle;
  const { verb } = deriveLeadEvent(listing, baseEvent);
  const fields = buildFields(listing);

  return (
    <ListingRowFrame
      listing={listing}
      fields={fields}
      matchIndicator={matchIndicator}
      leadSlot={
        <p className="text-base leading-snug">
          <strong className="font-bold">{coralName}</strong>{' '}
          <span className="font-normal">{verb}</span>{' '}
          <span>{listing.vendorDisplayName}</span>.
        </p>
      }
    />
  );
}
