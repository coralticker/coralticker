import type { MetadataRoute } from 'next';
import { getAllNamedCoralSlugs } from '@/lib/queries/named-corals';
import { getAllActiveVendorSlugs } from '@/lib/queries/vendors';
import { SITE_URL } from '@/lib/seo/site-url';

// CTK-162 scope (d): the sitemap lives here (CTK-017's parallel-bundle routing
// is dead — CTK-017 was never scaffolded; Jon ratified building it in CTK-162
// on 2026-06-20). Enumerates the static content/landing routes + the
// data-driven /coral/[slug] and /vendor/[slug] detail pages off the same
// catalog generateStaticParams rides. Designed to extend for the INV-02-gated
// /coral/[slug]/price-history + /guides/[slug] later — those routes don't exist
// yet, so they are intentionally NOT listed.
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
  { path: '/about', changeFrequency: 'monthly', priority: 0.5 },
  { path: '/signup', changeFrequency: 'monthly', priority: 0.5 },
];

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const [coralSlugs, vendorSlugs] = await Promise.all([
    getAllNamedCoralSlugs(),
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

  const vendorEntries: MetadataRoute.Sitemap = vendorSlugs.map(({ slug }) => ({
    url: `${SITE_URL}/vendor/${slug}`,
    changeFrequency: 'weekly',
    priority: 0.6,
  }));

  return [...staticEntries, ...coralEntries, ...vendorEntries];
}
