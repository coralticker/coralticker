// JSON-LD for /guides/[slug] — Article + author Person(Jon) (CTK-162 D-4, open
// item #4). DELIBERATELY no ItemList / Offer / AggregateOffer: the embedded coral
// refs carry live prices, but an aggregate priced list on an editorial page is a
// deceptive rich-result (coverage-claim bar + INV-05) — per-coral pages own the
// price structured data. A guide is a named-human Article, nothing more.
//
// Pure builder (siteUrl param, no '@/' value imports) so the co-located test runs
// under `node --test --experimental-strip-types`. serializeJsonLd is shared from
// coral-jsonld (the same `<`-escape guard).

export interface GuideJsonLdInput {
  siteUrl: string;
  slug: string;
  title: string;
  description: string | null;
  updated: string; // YYYY-MM-DD editorial-revision date
}

export function buildGuideJsonLd(input: GuideJsonLdInput): object[] {
  const url = `${input.siteUrl}/guides/${input.slug}`;
  const article: Record<string, unknown> = {
    '@context': 'https://schema.org',
    '@type': 'Article',
    headline: input.title,
    url,
    mainEntityOfPage: url,
    author: { '@type': 'Person', name: 'Jon' },
    publisher: { '@type': 'Organization', name: 'CoralTicker' },
  };
  if (input.updated) {
    article.dateModified = input.updated;
  }
  if (input.description) {
    article.description = input.description;
  }
  return [article];
}
