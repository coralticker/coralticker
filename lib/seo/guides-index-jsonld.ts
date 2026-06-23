// JSON-LD for the /guides index — CollectionPage + ItemList (CTK-183, mirrors
// the CTK-162 scope-d guide JSON-LD pattern). A summary-format ItemList of the
// guide pages — names + urls only, NO Offer/price/AggregateOffer. The same
// deceptive-rich-result guard as guide-jsonld.ts applies: an editorial index is
// a list of Articles, never a priced collection (INV-05).
//
// Pure builder (siteUrl param, no '@/' value imports) so the co-located test
// runs under `node --test --experimental-strip-types`. serializeJsonLd is shared
// from coral-jsonld (the same `<`-escape guard) — the caller imports it there.

export interface GuidesIndexJsonLdInput {
  siteUrl: string;
  // Rendered, sorted guide list — drives ItemList order + names so the structured
  // data scales automatically with the content dir (no per-guide JSON-LD edit).
  guides: { slug: string; title: string }[];
}

export function buildGuidesIndexJsonLd(input: GuidesIndexJsonLdInput): object[] {
  const url = `${input.siteUrl}/guides`;
  return [
    {
      '@context': 'https://schema.org',
      '@type': 'CollectionPage',
      name: 'Buying guides',
      url,
      mainEntity: {
        '@type': 'ItemList',
        itemListElement: input.guides.map((g, i) => ({
          '@type': 'ListItem',
          position: i + 1,
          url: `${input.siteUrl}/guides/${g.slug}`,
          name: g.title,
        })),
      },
    },
  ];
}
