// JSON-LD for /coral/[slug] — Product + AggregateOffer + BreadcrumbList
// (CTK-162 scope d). Pure builder: takes siteUrl as a param and imports only
// the Listing type (erased by strip-types), so the test runs under
// `node --test --experimental-strip-types` with no '@/' alias resolution — same
// shape as listing-price.ts. The caller (app/coral/[slug]/page.tsx) feeds
// SITE_URL in.
//
// INV-05 honesty guard (branding-guide.md §Short-copy "Coral-page SERP
// metadata"): AggregateOffer lowPrice/highPrice exclude auction rows and
// null/zero-price rows. Auction rows are already gone — getCoralAvailability
// filters `vl.is_auction = false` at the query (lib/queries/listings.ts) — so
// the guard here is the null/zero-price half plus the in-stock restriction. A
// variant-placeholder price emitted as a structured lowPrice would be a
// deceptive rich-result; the offer set is built from in-stock priced rows only,
// which also makes it stable across the ?include-oos=1 toggle (the toggle adds
// OOS rows; this filter drops them either way) and matches the canonical
// bare-route SERP card.

import type { Listing } from '@/lib/queries/listings';

export interface CoralJsonLdInput {
  siteUrl: string;
  canonicalName: string;
  description: string | null;
  slug: string;
  listings: Listing[];
}

export function buildCoralJsonLd(input: CoralJsonLdInput): object[] {
  const url = `${input.siteUrl}/coral/${input.slug}`;

  const product: Record<string, unknown> = {
    '@type': 'Product',
    name: input.canonicalName,
    url,
  };
  if (input.description) {
    product.description = input.description;
  }

  // INV-05: in-stock AND a real positive price. `> 0` matches the CTK-103 F1
  // currentPrice guard — a 0 lowPrice is as deceptive as a null one.
  const pricedInStock = input.listings.filter(
    (l) => l.inStock && l.currentPrice != null && l.currentPrice > 0,
  );
  if (pricedInStock.length > 0) {
    const prices = pricedInStock.map((l) => l.currentPrice as number);
    product.offers = {
      '@type': 'AggregateOffer',
      priceCurrency: 'USD',
      lowPrice: Math.min(...prices),
      highPrice: Math.max(...prices),
      offerCount: pricedInStock.length,
      availability: 'https://schema.org/InStock',
    };
  }

  const breadcrumb = {
    '@type': 'BreadcrumbList',
    itemListElement: [
      { '@type': 'ListItem', position: 1, name: 'Home', item: input.siteUrl },
      { '@type': 'ListItem', position: 2, name: 'Corals', item: `${input.siteUrl}/corals` },
      { '@type': 'ListItem', position: 3, name: input.canonicalName, item: url },
    ],
  };

  return [
    { '@context': 'https://schema.org', ...product },
    { '@context': 'https://schema.org', ...breadcrumb },
  ];
}

// Serialize for the <script type="application/ld+json"> payload. Escapes `<` so
// a </script> embedded in any field (canonical_name, description) can't break
// out of the tag — the standard Next.js JSON-LD guard. Both fields are curated
// today (canonical_name; description carries coral.lore per CTK-185(a)), so the
// escape isn't strictly reachable — but it stays as defense in depth: the source
// is curated text, not a hard guarantee, and the surface is new.
export function serializeJsonLd(jsonLd: object[]): string {
  return JSON.stringify(jsonLd).replace(/</g, '\\u003c');
}
