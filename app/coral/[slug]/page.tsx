import { Fragment } from 'react';
import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';
import { getGuidesFeaturingCoral, stripTrailingPeriod } from '@/lib/content/guides';
import {
  getAllNamedCoralSlugs,
  getCoralLastSeenAt,
  getNamedCoralBySlug,
} from '@/lib/queries/named-corals';
import {
  getCoralAvailability,
  getCoralInWindowVendorCount,
} from '@/lib/queries/listings';
import { parseIncludeOOS } from '@/lib/queries/listing-params';
import { DataRow } from '@/components/ui/data-row';
import { PageEyebrow } from '@/components/ui/page-eyebrow';
import { PageShell } from '@/components/ui/page-shell';
import { PageH1 } from '@/components/ui/page-h1';
import { SectionHeader } from '@/components/ui/section-header';
import { formatRelativeTime } from '@/lib/format/relative-time';
import { latestTimestamp } from '@/lib/format/latest-timestamp';
import { buildLineageFields } from '@/lib/format/lineage-fields';
import { pluralize } from '@/lib/format/pluralize';
import { distinctInStockVendorCount } from '@/lib/format/vendor-count';
import { buildCoralJsonLd, serializeJsonLd } from '@/lib/seo/coral-jsonld';
import { SITE_URL } from '@/lib/seo/site-url';
import { VendorAvailabilityRow } from './_components/vendor-availability-row';

// The searchParams await suppresses prerender for the WHOLE route: despite
// generateStaticParams and the build table's ● glyph, the build emits no
// /coral/<slug> static HTML. Every request server-renders;
// getCoralAvailability's unstable_cache wrap (revalidate 300, key carries
// toggle state) is the load-bearing cache. The const below is inert for
// serving today — kept so the cadence intent survives if the route ever
// regains static prerendering.
export const revalidate = 300;

interface PageProps {
  params: Promise<{ slug: string }>;
  searchParams: Promise<{
    'include-oos'?: string;
  }>;
}

export async function generateStaticParams(): Promise<{ slug: string }[]> {
  return getAllNamedCoralSlugs();
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { slug } = await params;
  const coral = await getNamedCoralBySlug(slug);
  if (!coral) {
    // 404 copy duplicated at ./not-found.tsx metadata export — edit both or
    // neither. This null-branch is RSC-flight-only; not-found.tsx paints the
    // rendered head and is the keeper if one ever goes.
    return {
      title: 'Coral not in seed list', // suffix via root title.template
      description:
        "This coral isn't in the seed list yet. I'm working through the long tail.",
    };
  }
  return {
    // Enriched SERP strings per branding-guide.md §Short-copy "Coral-page SERP
    // metadata" (Jon-approved 2026-06-20). Keyword intent lives in title + meta
    // + JSON-LD, never the H1. Comma-not-em-dash inside {specific} so the root
    // title.template suffix (" — CoralTicker") is the only dash. No "cheapest"
    // superlative — the page ranks for it off the body ladder + JSON-LD, never
    // claims it (coverage-claim bar).
    title: `${coral.canonical_name}, current price across reef vendors`, // suffix via root title.template
    description: `Where to buy ${coral.canonical_name}: compare current prices across reef coral vendors and get a drop alert when it lists.`,
    // Canonical = bare route — the ?include-oos=1 toggle variant resolves to
    // the bare-route SERP card.
    alternates: {
      canonical: `/coral/${slug}`,
    },
    openGraph: {
      url: `/coral/${slug}`,
      siteName: 'CoralTicker',
      type: 'website',
      locale: 'en_US',
    },
    twitter: { card: 'summary' },
  };
}

const EMPTY_FALLBACK =
  "Nothing in stock right now. I'll surface it when it lists.";

// Always rendered — consistent chrome across populated/empty states.
function IncludeOOSToggle({
  slug,
  includeOOS,
}: {
  slug: string;
  includeOOS: boolean;
}) {
  const linkClass =
    'hover:underline focus-visible:underline underline-offset-[3px] decoration-1';
  const activeClass = 'underline underline-offset-[3px] decoration-1';
  return (
    <nav
      aria-label="Availability filter"
      className="pt-2 pb-2 font-mono text-sm uppercase tracking-[0.08em] text-ink"
    >
      <Link
        href={includeOOS ? `/coral/${slug}` : `/coral/${slug}?include-oos=1`}
        className={includeOOS ? activeClass : linkClass}
        aria-current={includeOOS ? 'true' : undefined}
      >
        INCLUDE OUT OF STOCK
      </Link>
    </nav>
  );
}

export default async function CoralPage({ params, searchParams }: PageProps) {
  const { slug } = await params;
  const sp = await searchParams;
  const includeOOS = parseIncludeOOS(sp['include-oos']);
  const coral = await getNamedCoralBySlug(slug);
  if (!coral) notFound();

  // Availability + the second-signal count fire concurrently. The count is a
  // cheap COUNT behind its own 300s unstable_cache, so the speculative fire on
  // the populated majority path costs at most one extra cached query per coral
  // per window. Accepted coupling: a count failure now rejects the whole render
  // even when the value goes unconsumed — same Neon, same request; the marginal
  // exposure (count fails while availability succeeds) is narrow.
  const [listings, inWindowVendorCount] = await Promise.all([
    getCoralAvailability(coral.id, includeOOS),
    getCoralInWindowVendorCount(coral.id),
  ]);
  const lineageFields = buildLineageFields(coral);
  const hasListings = listings.length > 0;

  // Reverse index: the guides that feature this coral, for the crawlable
  // "Featured in:" back-link (the SEO point — real internal coral→guide edges).
  // Derived from the MDX bodies at read-time, so it stays correct as guides change.
  const featuredInGuides = getGuidesFeaturingCoral(slug);

  // Product + AggregateOffer + BreadcrumbList (CTK-162 scope d). Offers are
  // built from in-stock priced rows only (INV-05 guard inside the builder), so
  // the structured lowPrice is stable across the ?include-oos=1 toggle and
  // matches the canonical bare-route card.
  const jsonLd = buildCoralJsonLd({
    siteUrl: SITE_URL,
    canonicalName: coral.canonical_name,
    description: coral.description,
    slug,
    listings,
  });

  // Three availability states per branding-guide §"Eyebrow shape + slot" +
  // §"Section transitions". Branch order: populated (ANY in-stock row) →
  // all-OOS (in-window rows exist, none in stock) → empty (zero in-window
  // listings; NOT LISTED / "Currently unavailable." reserved for this state —
  // they were false over an all-OOS set). State classifies by stock, not by
  // rendered-row count, so the toggled-on view of an all-OOS set also reads
  // "Currently out of stock."
  //
  // oosVendorCount is now a STATE-FORK signal only — isAllOOS forks on it (an
  // all-OOS set with in-window carriers vs. a truly-not-listed coral). It is no
  // longer rendered: post-CTK-187 the all-OOS eyebrow is the bare state word,
  // not "{N} VENDORS · ALL OUT OF STOCK" (the carrier count read as present-tense
  // availability beside an empty default buy-view — Tier-1B). The fork still
  // needs "are there in-window OOS carriers at all?": rendered rows when toggled
  // on, the stock-unfiltered count query when the default view excludes them
  // (separate cheap signal, do NOT widen the default availability query). The
  // count fires unconditionally in the Promise.all above; its value is consumed
  // only on the innermost leaf (no in-stock row AND zero rendered rows).
  const hasInStockRow = listings.some((l) => l.inStock);
  const oosVendorCount = hasInStockRow
    ? 0
    : hasListings
      ? new Set(listings.map((l) => l.vendorSlug)).size
      : inWindowVendorCount;
  const isAllOOS = !hasInStockRow && oosVendorCount > 0;

  // Populated-arm count = distinct IN-STOCK vendors (CTK-187), not the listing-
  // row count: three in-stock frags from one shop read "1 VENDOR". The inStock
  // filter is load-bearing on the toggled-on view, where listings carries OOS
  // rows the count must exclude. Shared helper so #1 (here) and #2 (the
  // /guides market line) cannot drift on the in-stock rule.
  const inStockVendorCount = distinctInStockVendorCount(listings);

  const sectionHeader = hasInStockRow
    ? 'Currently available.'
    : isAllOOS
      ? 'Currently out of stock.'
      : 'Currently unavailable.';

  const now = new Date();
  const lastSeenAt =
    hasInStockRow || isAllOOS ? null : await getCoralLastSeenAt(coral.id);
  // All-OOS eyebrow: bare state word, no count (CTK-187) — the count chunk it
  // previously carried read as present-tense availability beside an empty
  // default buy-view. Freshness chunk omitted ("last seen" is ambiguous across
  // an all-OOS set; per-row Listed. carries it once toggled on). The carrier
  // signal now lives on the price-history eyebrow + the INCLUDE OUT OF STOCK
  // body toggle.
  // LATEST = max(firstSeenAt) over the set — the buy-intent ladder orders
  // cheapest-first, so index 0 is no longer the newest row.
  const eyebrowChunks = hasInStockRow
    ? [
        `${inStockVendorCount} ${pluralize(inStockVendorCount, 'VENDOR', 'VENDORS')}`,
        `LATEST ${formatRelativeTime(latestTimestamp(listings, (l) => l.firstSeenAt), now).toUpperCase()}`,
      ]
    : isAllOOS
      ? ['ALL OUT OF STOCK']
      : lastSeenAt === null
        ? ['NOT LISTED']
        : ['NOT LISTED', `LAST SEEN ${formatRelativeTime(lastSeenAt, now).toUpperCase()}`];

  return (
    <PageShell as="article">
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: serializeJsonLd(jsonLd) }}
      />
      <PageEyebrow chunks={eyebrowChunks} />
      <PageH1 className="mb-4">
        {coral.canonical_name}
      </PageH1>

      {lineageFields.length > 0 ? (
        <div className="mb-6">
          <DataRow fields={lineageFields} />
        </div>
      ) : null}

      {coral.description !== null ? (
        <p className="text-base leading-relaxed mb-8">{coral.description}</p>
      ) : null}

      {/* Contextual back-link to any buying guide that features this coral
          (CTK-184 part b). Crawlable <Link> — a real internal coral→guide edge,
          the SEO point. Derived from the guide MDX, so it tracks editorial
          changes; renders nothing when no guide features the coral. */}
      {featuredInGuides.length > 0 ? (
        <p className="text-base leading-relaxed mb-8">
          Featured in:{' '}
          {featuredInGuides.map((guide, i) => (
            <Fragment key={guide.frontmatter.slug}>
              {i > 0 ? ', ' : ''}
              <Link
                href={`/guides/${guide.frontmatter.slug}`}
                className="text-ink underline underline-offset-2 decoration-1"
              >
                {stripTrailingPeriod(guide.frontmatter.title)}
              </Link>
            </Fragment>
          ))}
        </p>
      ) : null}

      <SectionHeader className="mt-10">
        {sectionHeader}
      </SectionHeader>

      <IncludeOOSToggle slug={slug} includeOOS={includeOOS} />

      {/* Link to this coral's price-history child route (CTK-162). Top of the
          price block — anchored to the cheapest-price context that motivates the
          click, above the ladder. Content register (sentence-case Plex Sans,
          underline-at-rest) so it reads as navigation, distinct from the
          mono-uppercase OOS control above; /brand-manager ruling 2026-06-21 (D-3).
          No arrow (reserved for outbound). Shown unconditionally — the
          destination renders a real chart or its own thin-history state. */}
      <p className="mt-3 mb-2 text-sm">
        <Link href={`/coral/${slug}/price-history`} className="underline">
          See price history
        </Link>
      </p>

      {hasListings ? (
        <div>
          {listings.map((listing) => (
            <VendorAvailabilityRow key={listing.id} listing={listing} />
          ))}
        </div>
      ) : isAllOOS ? (
        // One-line hint per branding-guide §"Section transitions" third state —
        // without it the state is a dead end (eyebrow says N vendors carry it,
        // default view shows no rows). Mono-uppercase phrase names the literal
        // toggle label.
        <p role="status" className="text-base text-ink py-6">
          All listings are out of stock right now &mdash;{' '}
          <span className="font-mono text-sm uppercase tracking-[0.08em]">
            INCLUDE OUT OF STOCK
          </span>{' '}
          shows them.
        </p>
      ) : (
        <p role="status" className="text-base text-ink py-6">
          {EMPTY_FALLBACK}
        </p>
      )}

      {/* The canonical match-provenance copy lives in the /corals "About this
          list." block — link, never duplicate. */}
      <p className="mt-4 text-sm">
        Matched by name to{' '}
        <Link href="/corals#about-this-list" className="underline">
          a list I researched by hand
        </Link>
        .
      </p>

      {coral.source_urls !== null && coral.source_urls.length > 0 ? (
        <footer className="mt-12 text-sm">
          <SectionHeader>
            Sources.
          </SectionHeader>
          <ul className="space-y-1">
            {coral.source_urls.map((url) => (
              <li key={url}>
                <a
                  href={url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="underline break-words"
                >
                  {url}
                </a>
              </li>
            ))}
          </ul>
        </footer>
      ) : null}
    </PageShell>
  );
}
