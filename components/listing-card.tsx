// §3.5.1 <ListingCard> — 3-view fanout (/, /new, /deals)
//
// Renders the brand's listing card per site.md §3.5.1 + branding-guide.md
// §"Lead + row composition" + §"Em-dash data row format" + §"State markers".
//
// Lead sentence shapes (brand-canon — branding-guide.md line 231):
//   just-listed   → **{coral}** listed at {vendor}.
//   back-in-stock → **{coral}** back in stock at {vendor}.
//   price-dropped → **{coral}** price dropped — was ${priorPrice}, now ${currentPrice}.
// Price-dropped sentence does NOT include vendor — the new $Y is the headline.
// Vendor is recoverable via image alt + Ref field + card grouping.
//
// Coral name: namedCoralCanonicalName ?? rawTitle. DataRow fields constructed
// internally per the discriminator: Ref / Price / Listed / Lineage (conditional).
// Listed timestamp = event === 'just-listed' ? firstSeenAt : observedAt.
// CaveatLabel rendered when match is name-based (matchConfidence in
// fuzzy/manual/null AND namedCoralCanonicalName non-null).
//
// Image via next/image unoptimized per arch-v1 #53 with explicit width/height/sizes.
// Whole row is a link to productUrl — vendor-traffic-respect per branding-guide.md.

import Image from 'next/image';
import { CaveatLabel } from '@/components/ui/caveat-label';
import { DataRow, type DataRowField } from '@/components/ui/data-row';
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

function buildFields(props: ListingCardProps): DataRowField[] {
  const { listing, event } = props;
  const fields: DataRowField[] = [
    { label: 'Ref', value: derivedRef(listing.productUrl) },
  ];

  if (event === 'price-dropped') {
    fields.push({
      label: 'Price',
      value: {
        kind: 'price-drop-new',
        oldValue: formatPrice(props.priorPrice),
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
  const coralName = listing.namedCoralCanonicalName ?? listing.rawTitle;
  const altText = listing.namedCoralCanonicalName
    ? `${listing.vendorDisplayName} listing of ${listing.namedCoralCanonicalName}`
    : `${listing.vendorDisplayName} listing — ${listing.rawTitle}`;
  const fields = buildFields(props);

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
