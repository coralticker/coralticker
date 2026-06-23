import type { Metadata } from 'next';
import Link from 'next/link';
import { getAllGuides, updatedMonthYear } from '@/lib/content/guides';
import { PageShell } from '@/components/ui/page-shell';
import { PageEyebrow } from '@/components/ui/page-eyebrow';
import { PageH1 } from '@/components/ui/page-h1';
import { SocialLinks } from '@/components/ui/social-links';
import { buildGuidesIndexJsonLd } from '@/lib/seo/guides-index-jsonld';
import { serializeJsonLd } from '@/lib/seo/coral-jsonld';
import { SITE_URL } from '@/lib/seo/site-url';

// Static index: renders no live <CoralReference> data (the per-guide bodies do,
// behind their own caches). The row's `updated` is editorial frontmatter, not a
// price-freshness claim — so no `revalidate`; this page is a build-time render.

// Per-guide blurb, hardcoded per-slug (v1, one guide). NOT a frontmatter field
// (Jon's call) — the index owns its own editorial hook, distinct from the guide's
// SERP description. Add a row here when a new guide ships.
const GUIDE_BLURBS: Record<string, string> = {
  'most-hunted-acros-2026':
    "The Acropora names that sell out in the first minute — and what they're going for right now.",
};

export const metadata: Metadata = {
  title: 'Buying guides', // suffix via root title.template
  description:
    'A few longer reads on corals worth knowing — opinionated, sourced, and updated when my read changes.',
  alternates: { canonical: '/guides' },
  openGraph: { url: '/guides', siteName: 'CoralTicker', type: 'website', locale: 'en_US' },
  twitter: { card: 'summary' },
};

export default function GuidesIndex() {
  const guides = getAllGuides(); // newest-revised first, null-dropped (see lib)

  // CollectionPage/ItemList built off the rendered list — scales with the content
  // dir, no per-guide edit. Same serialize + <script> shape as the [slug] page.
  const jsonLd = buildGuidesIndexJsonLd({
    siteUrl: SITE_URL,
    guides: guides.map(({ frontmatter: { slug, title } }) => ({ slug, title })),
  });

  return (
    <PageShell as="section">
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: serializeJsonLd(jsonLd) }}
      />
      <PageEyebrow chunks={['GUIDES']} />
      <PageH1 className="mb-8">Buying guides.</PageH1>

      <div className="text-base leading-relaxed space-y-4">
        <p>
          A few longer reads on corals worth knowing — what&apos;s worth
          chasing, what a name actually covers, and what each one&apos;s been
          doing across the vendors I check. One reefer&apos;s take: opinionated,
          sourced, and updated when my read changes.
        </p>
      </div>

      <ul className="list-none p-0 mt-10 space-y-0">
        {guides.map(({ frontmatter: { slug, kind, updated, title } }) => (
          <li key={slug} className="border-t border-line py-6 first:border-t-0 first:pt-0">
            <PageEyebrow
              chunks={[kind, ...(updated ? [`UPDATED ${updatedMonthYear(updated)}`] : [])]}
            />
            <h2 className="text-xl md:text-2xl font-bold">
              <Link href={`/guides/${slug}`} className="hover:text-forest">
                {title}
              </Link>
            </h2>
            {GUIDE_BLURBS[slug] && (
              <p className="mt-2 text-base leading-relaxed text-ink">{GUIDE_BLURBS[slug]}</p>
            )}
          </li>
        ))}
      </ul>

      <div className="mt-10 text-base leading-relaxed space-y-4">
        <p>
          I write these as I go, so the list is short on purpose — more when a
          topic earns one. If there&apos;s one you want sooner, hit me up on
          Discord.
        </p>
        <SocialLinks />
      </div>
    </PageShell>
  );
}
