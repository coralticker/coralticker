// <ListingCard> — single composition for the public-feed event-row across
// /deals, /new, and the homepage strip. Lead and Price both derive from
// listing fields per the precedence chain (CTK-047 Q3 lead-promotion lock
// 2026-06-03; see branding-guide.md §"Vendor-side sale markdown state-marker"
// → "Lead promotion on strikethrough Price."):
//
//   OOS (invalidated): lead = baseEvent ("listed at" / "back in stock at"),
//     Price = invalidated. OOS does NOT promote the lead per branding-guide
//     L230 invalidation semantic — supersedes Q3 promotion semantic.
//   CT-observed price-drop (priorPrice + priceDropObservedAt non-null):
//     lead = "price dropped at", Price = price-drop-new (oldValue = priorPrice).
//   Vendor-markdown ≥5% (compareAtPrice >= currentPrice * 1.05): lead =
//     "price dropped at" (Q3 lead promotion), Price = vendor-markdown
//     (oldValue = compareAtPrice).
//   Otherwise: lead = baseEvent, Price = bare current price.
//
// Vendor surfaces inline in the lead on every variant via parallel
// `at {vendor}.` grammar (CTK-047 Q1 lock 2026-06-02).
//
// baseEvent prop carries the back-in-stock vs. just-listed hint from the
// caller (e.g., /new's RPC arrival.event mapped through). The composition
// overrides with "price dropped at" via the derivation rule above; baseEvent
// only fires for non-price-drop rows. /deals + homepage strip pass no
// baseEvent and accept the 'just-listed' default — neither surface
// distinguishes restock vs. first-listing at the lead level (composition
// reads Price-shape signals from listing fields instead).

import { type DataRowField } from '@/components/ui/data-row';
import { ListingRowFrame } from '@/components/ui/listing-row-frame';
import { resolveOriginVendor } from '@/lib/format/origin-vendor';
import type { Listing } from '@/lib/queries/listings';

interface ListingCardProps {
  listing: Listing;
  baseEvent?: 'just-listed' | 'back-in-stock';
  matchIndicator?: boolean;
}

function formatPrice(value: number | null): string {
  if (value === null) return 'price on request';
  return `$${value.toFixed(2)}`;
}

function deriveLeadEvent(
  listing: Listing,
  baseEvent: 'just-listed' | 'back-in-stock' = 'just-listed',
): { verb: string; isPriceDropped: boolean } {
  // OOS does NOT promote (invalidated semantic per branding-guide L230 +
  // Q3 OOS-non-promotion precision lock 2026-06-03).
  if (!listing.inStock) {
    return {
      verb: baseEvent === 'just-listed' ? 'listed at' : 'back in stock at',
      isPriceDropped: false,
    };
  }
  // CT-observed price-drop wins over Q3 vendor-markdown promotion when both
  // could apply (the listing actually moved within the 24h window).
  if (listing.priorPrice !== null && listing.priceDropObservedAt !== null) {
    return { verb: 'price dropped at', isPriceDropped: true };
  }
  // Q3 promotion — vendor-markdown strikethrough promotes the lead.
  // Float-imprecision rewrite per /code-review Finding (2026-06-03): the
  // straightforward `compareAtPrice >= currentPrice * 1.05` form silently
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

function buildFields(listing: Listing, isOutOfStock: boolean): DataRowField[] {
  const fields: DataRowField[] = [];

  // Price precedence chain stays verbatim per CTK-047 Q3 directive — Q3
  // changes the LEAD derivation only, not the Price field. OOS > price-drop-
  // new > vendor-markdown > bare. currentPrice !== null guards auction rows
  // (project_auctions_in_scope.md L4 parse-side).
  if (isOutOfStock) {
    fields.push({
      label: 'Price',
      value: { kind: 'invalidated', value: formatPrice(listing.currentPrice) },
    });
  } else if (listing.priorPrice !== null && listing.currentPrice !== null) {
    fields.push({
      label: 'Price',
      value: {
        kind: 'price-drop-new',
        oldValue: formatPrice(listing.priorPrice),
        newValue: formatPrice(listing.currentPrice),
      },
    });
  } else if (
    listing.compareAtPrice !== null &&
    listing.currentPrice !== null &&
    (listing.compareAtPrice - listing.currentPrice) >=
      listing.currentPrice * 0.05 - 1e-9
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

  fields.push({
    label: 'Listed',
    value: {
      kind: 'relative-time',
      timestamp: listing.eventAt ?? listing.firstSeenAt,
    },
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

export function ListingCard({ listing, baseEvent, matchIndicator }: ListingCardProps) {
  const isOutOfStock = !listing.inStock;
  const coralName = listing.namedCoralCanonicalName ?? listing.rawTitle;
  const { verb } = deriveLeadEvent(listing, baseEvent);
  const fields = buildFields(listing, isOutOfStock);

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
