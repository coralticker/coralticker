import type { MetadataRoute } from 'next';
import {
  getSitemapCoralSlugs,
  getPriceHistorySitemapSlugs,
} from '@/lib/queries/named-corals';
import { getAllActiveVendorSlugs } from '@/lib/queries/vendors';
import { getAllGuideSlugs } from '@/lib/content/guides';
import { SITE_URL } from '@/lib/seo/site-url';

// CTK-162 scope (d): the sitemap lives here (CTK-017's parallel-bundle routing
// is dead — CTK-017 was never scaffolded; Jon ratified building it in CTK-162
// on 2026-06-20). Enumerates the static content/landing routes + the
// data-driven /vendor/[slug] detail pages, the in-window-gated /coral/[slug]
// set, the non-thin-gated /coral/[slug]/price-history child set, and the
// /guides/[slug] editorial pages (every authored .mdx, no stock gate).
//
// Two DIFFERENT coral gates, by design:
//   * /coral/[slug] — getSitemapCoralSlugs: in-window-coupled to
//     CORAL_RECENCY_DAYS; never-/stale-listed seed corals render thin pages and
//     are excluded to avoid a soft-404 signal (PR #21 /code-review F1).
//   * /coral/[slug]/price-history — getPriceHistorySitemapSlugs: gated on
//     history DEPTH (>= 2 envelope days = non-thin chart), NOT current stock. A
//     coral can be in the price-history set but absent from the parent set (rich
//     history, OOS today) — the price-history page's parent back-link prevents
//     the SEO orphan that would otherwise create.
// Both are NOT the full /coral/[slug] route set: generateStaticParams stays
// ungated so those pages still resolve when hit directly.
//
// No lastModified: there's no cheap honest per-page "updated" signal (a
// fabricated now() on every entry is worse than omitting it). Refreshed on a
// daily revalidate so newly-seeded corals / activated vendors enter the map.
export const revalidate = 86400;

// Excluded by design: /search (query-param results, not a canonical surface),
// /signup/confirmed (transient post-action), and the route handlers
// (/confirm, /unsubscribe — not indexable pages).
const STATIC_ROUTES: Array<{
  path: string;
  changeFrequency: MetadataRoute.Sitemap[number]['changeFrequency'];
  priority: number;
}> = [
  { path: '', changeFrequency: 'daily', priority: 1.0 },
  { path: '/deals', changeFrequency: 'daily', priority: 0.9 },
  { path: '/new', changeFrequency: 'daily', priority: 0.9 },
  { path: '/corals', changeFrequency: 'weekly', priority: 0.7 },
  { path: '/vendors', changeFrequency: 'weekly', priority: 0.7 },
  // /guides index — matches the /corals + /vendors index priority. The
  // /guides/[slug] entries are mapped separately below (getAllGuideSlugs); this
  // is the index route only, no duplication.
  { path: '/guides', changeFrequency: 'weekly', priority: 0.7 },
  { path: '/about', changeFrequency: 'monthly', priority: 0.5 },
  { path: '/signup', changeFrequency: 'monthly', priority: 0.5 },
];

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const [coralSlugs, priceHistorySlugs, vendorSlugs] = await Promise.all([
    getSitemapCoralSlugs(),
    getPriceHistorySitemapSlugs(),
    getAllActiveVendorSlugs(),
  ]);

  const staticEntries: MetadataRoute.Sitemap = STATIC_ROUTES.map((r) => ({
    url: `${SITE_URL}${r.path}`,
    changeFrequency: r.changeFrequency,
    priority: r.priority,
  }));

  const coralEntries: MetadataRoute.Sitemap = coralSlugs.map(({ slug }) => ({
    url: `${SITE_URL}/coral/${slug}`,
    changeFrequency: 'weekly',
    priority: 0.6,
  }));

  // Price-history child pages — a notch below the parent coral (0.6): a derived
  // analytical surface, not the canonical buy-intent page.
  const priceHistoryEntries: MetadataRoute.Sitemap = priceHistorySlugs.map(
    ({ slug }) => ({
      url: `${SITE_URL}/coral/${slug}/price-history`,
      changeFrequency: 'weekly',
      priority: 0.5,
    }),
  );

  const vendorEntries: MetadataRoute.Sitemap = vendorSlugs.map(({ slug }) => ({
    url: `${SITE_URL}/vendor/${slug}`,
    changeFrequency: 'weekly',
    priority: 0.6,
  }));

  // /guides/[slug] — data-driven off the content dir (every authored .mdx). No
  // thin-gate (a guide is durable editorial content, not a stock-dependent page);
  // changeFrequency monthly matches the editorial-revision cadence.
  const guideEntries: MetadataRoute.Sitemap = getAllGuideSlugs().map(({ slug }) => ({
    url: `${SITE_URL}/guides/${slug}`,
    changeFrequency: 'monthly',
    priority: 0.6,
  }));

  return [
    ...staticEntries,
    ...coralEntries,
    ...priceHistoryEntries,
    ...vendorEntries,
    ...guideEntries,
  ];
}
