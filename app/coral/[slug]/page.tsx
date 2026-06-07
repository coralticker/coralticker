import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';
import {
  getAllNamedCoralSlugs,
  getCoralLastSeenAt,
  getNamedCoralBySlug,
} from '@/lib/queries/named-corals';
import {
  getCoralAvailability,
  getCoralInWindowVendorCount,
} from '@/lib/queries/listings';
import { DataRow } from '@/components/ui/data-row';
import { PageEyebrow } from '@/components/ui/page-eyebrow';
import { formatRelativeTime } from '@/lib/format/relative-time';
import { latestTimestamp } from '@/lib/format/latest-timestamp';
import { buildLineageFields } from '@/lib/format/lineage-fields';
import { VendorAvailabilityRow } from './_components/vendor-availability-row';

// CTK-047 B-2 — medal-bearing surface; cadence equalized to 5min with /deals
// + /vendor/[slug] + homepage strip per /lead-architect 2026-06-02.
//
// CTK-126 D-2 (2026-06-05): availability defaults to in-stock rows; the
// INCLUDE OUT OF STOCK toggle (?include-oos=1) restores the inventory-recon
// mixed render — single-axis variant of the CTK-098 <SortFilterBar> third
// axis, toggle ONLY per the 2026-06-05 chrome-scope ruling (no SORT/FILTER
// axes at 1-6 rows). The searchParams read flips the route pure-dynamic at
// runtime, so getCoralAvailability now carries the unstable_cache wrap
// (revalidate 300, key carries toggle state) per the CTK-046 /vendor/[slug]
// precedent — the page-level revalidate no longer is the data-cache TTL.
export const revalidate = 300;

interface PageProps {
  params: Promise<{ slug: string }>;
  searchParams: Promise<{
    'include-oos'?: string;
  }>;
}

function parseIncludeOOS(raw: string | undefined): boolean {
  return raw === '1';
}

export async function generateStaticParams(): Promise<{ slug: string }[]> {
  return getAllNamedCoralSlugs();
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { slug } = await params;
  const coral = await getNamedCoralBySlug(slug);
  if (!coral) {
    return {
      title: 'Coral not in seed list', // suffix via root title.template
      description:
        "This coral isn't in the seed list yet. I'm working through the long tail.",
    };
  }
  return {
    title: `${coral.canonical_name} — current vendor availability`, // suffix via root title.template
    description: `Current vendor availability and pricing for ${coral.canonical_name}. Drop alerts across reef coral vendors.`,
    // Canonical = bare route per the /vendor/[slug] precedent — the
    // ?include-oos=1 toggle variant resolves to the bare-route SERP card.
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

// CTK-126 D-2 — single-axis toggle chrome per the CTK-098 <SortFilterBar>
// third-axis pattern (mono uppercase register, underline-on-active,
// click-active-to-clear via canonical-chain bare-route). Toggle ONLY — no
// SORT/FILTER axes per the 2026-06-05 chrome-scope ruling. Always rendered
// (consistent chrome across populated/empty states, same as SortFilterBar).
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

  const listings = await getCoralAvailability(coral.id, includeOOS);
  const lineageFields = buildLineageFields(coral);
  const hasListings = listings.length > 0;

  // CTK-126 fold (/code-review #1, Tier 1A) — three availability states per
  // branding-guide §"Eyebrow shape + slot" + §"Section transitions" (third
  // state locked /brand-manager 2026-06-05). Branch order: populated (ANY
  // in-stock row) → all-OOS (in-window rows exist, none in stock) → empty
  // (zero in-window listings; NOT LISTED / "Currently unavailable." now
  // reserved for this state — they were false over an all-OOS set, the live
  // defect). State classifies by stock, not by rendered-row count, so the
  // toggled-on view of an all-OOS set also reads "Currently out of stock."
  // N = distinct vendors across the in-window (all-OOS) set: derived from
  // the rendered rows when toggled on, from the stock-unfiltered count query
  // when the default view excludes them (/lead-backend call — separate cheap
  // signal, do NOT widen the default availability query).
  const hasInStockRow = listings.some((l) => l.inStock);
  const oosVendorCount = hasInStockRow
    ? 0
    : hasListings
      ? new Set(listings.map((l) => l.vendorSlug)).size
      : await getCoralInWindowVendorCount(coral.id);
  const isAllOOS = !hasInStockRow && oosVendorCount > 0;

  const sectionHeader = hasInStockRow
    ? 'Currently available.'
    : isAllOOS
      ? 'Currently out of stock.'
      : 'Currently unavailable.';

  const now = new Date();
  const lastSeenAt =
    hasInStockRow || isAllOOS ? null : await getCoralLastSeenAt(coral.id);
  // All-OOS eyebrow: count chunk keeps continuity with the populated state;
  // freshness chunk omitted ("last seen" is ambiguous across an all-OOS set;
  // per-row Listed. carries it once toggled on) per the eyebrow-slot lock.
  // CTK-127 fold #1 (Tier 1A): LATEST = max(firstSeenAt) over the set — the
  // buy-intent ladder orders cheapest-first, so index 0 is no longer the
  // newest row.
  const eyebrowChunks = hasInStockRow
    ? [
        `${listings.length} ${listings.length === 1 ? 'VENDOR' : 'VENDORS'}`,
        `LATEST ${formatRelativeTime(latestTimestamp(listings, (l) => l.firstSeenAt), now).toUpperCase()}`,
      ]
    : isAllOOS
      ? [
          `${oosVendorCount} ${oosVendorCount === 1 ? 'VENDOR' : 'VENDORS'}`,
          'ALL OUT OF STOCK',
        ]
      : lastSeenAt === null
        ? ['NOT LISTED']
        : ['NOT LISTED', `LAST SEEN ${formatRelativeTime(lastSeenAt, now).toUpperCase()}`];

  return (
    <main className="px-6 py-12 max-w-3xl mx-auto">
      <PageEyebrow chunks={eyebrowChunks} />
      <h1 className="text-3xl md:text-4xl font-bold mb-4">
        {coral.canonical_name}
      </h1>

      {lineageFields.length > 0 ? (
        <div className="mb-6">
          <DataRow fields={lineageFields} />
        </div>
      ) : null}

      {coral.description !== null ? (
        <p className="text-base leading-relaxed mb-8">{coral.description}</p>
      ) : null}

      <div className="mt-10 mb-2">
        <h2 className="text-sm font-bold pb-2 border-b border-line">
          {sectionHeader}
        </h2>
      </div>

      <IncludeOOSToggle slug={slug} includeOOS={includeOOS} />

      {hasListings ? (
        <div>
          {listings.map((listing) => (
            <VendorAvailabilityRow key={listing.id} listing={listing} />
          ))}
        </div>
      ) : isAllOOS ? (
        // Locked one-line hint per branding-guide §"Section transitions"
        // third state — without it the state is a dead end (eyebrow says N
        // vendors carry it, default view shows no rows). Mono-uppercase
        // phrase names the literal toggle label.
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

      {/* CTK-126 — match-provenance pointer. One line; the canonical copy
          lives in the /corals "About this list." block (links, never
          duplicates). Link rides the phrase per the rev1 lock, underlined
          at rest per branding-guide L196 link default (the /corals row-stack
          hover-only carve-out doesn't reach prose links). */}
      <p className="mt-4 text-sm">
        Matched by name to{' '}
        <Link href="/corals#about-this-list" className="underline">
          a list I researched by hand
        </Link>
        .
      </p>

      {coral.source_urls !== null && coral.source_urls.length > 0 ? (
        <footer className="mt-12 text-sm">
          <h2 className="text-sm font-bold pb-2 mb-2 border-b border-line">
            Sources.
          </h2>
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
    </main>
  );
}
