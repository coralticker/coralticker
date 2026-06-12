import type { Metadata } from 'next';
import { cache } from 'react';
import { Suspense, type ReactNode } from 'react';
import { ListingCard } from '@/components/listing-card';
import { GroupDivider } from '@/components/group-divider';
import { DataRowSkeleton } from '@/components/ui/data-row-skeleton';
import { PageEyebrow, PageEyebrowSkeleton } from '@/components/ui/page-eyebrow';
import { SortFilterBar } from '@/components/ui/sort-filter-bar';
import { PageH1 } from '@/components/ui/page-h1';
import { buildBucketedRows, DIVIDER_THRESHOLD } from '@/lib/format/group-bucket';
import { formatRelativeTime } from '@/lib/format/relative-time';
import { formatTypeLabel } from '@/lib/format/type-label';
import { latestTimestamp } from '@/lib/format/latest-timestamp';
import { pluralize } from '@/lib/format/pluralize';
import {
  chromeCategoryLabel,
  parseCategory,
  parseSort,
} from '@/lib/queries/listing-params';
import {
  DEALS_WINDOW_DAYS,
  getLatestPriceDropAt,
  getRecentPriceDrops,
  type ListingCategory,
  type ListingSort,
  type PriceDropListing,
} from '@/lib/queries/listings';

// The searchParams read below flips this route dynamic at runtime;
// getRecentPriceDrops' unstable_cache wrap keyed on (sort, category) carries
// the 300s data cadence.
export const revalidate = 300;

export const metadata: Metadata = {
  title: 'Coral price drops', // suffix via root title.template
  description:
    'Price drops across reef coral vendors. One feed.',
  alternates: { canonical: '/deals' },
  openGraph: { url: '/deals', siteName: 'CoralTicker', type: 'website', locale: 'en_US' },
  twitter: { card: 'summary' },
};

interface PageProps {
  searchParams: Promise<{ sort?: string; category?: string }>;
}

const SKELETON_ROW_COUNT = 6;

// User-facing window copy derives from the exported constant the RPC binds
// (one-constant pattern), so it can't drift from the actual window.
// Singular-guarded against a hypothetical 1-day window.
const PRICE_DROP_WINDOW =
  DEALS_WINDOW_DAYS === 1 ? '1 day' : `${DEALS_WINDOW_DAYS} days`;

const DOWNTIME_FALLBACK = `No price drops in the last ${PRICE_DROP_WINDOW}. I'll surface them as vendors update.`;

// Arg-taking is load-bearing: a no-arg wrapper would serve one cached shape
// for all filter states in a request tree; React cache() keys per-request
// dedup by the (sort, category) args.
const dropsCached = cache(
  (sort: ListingSort, category: ListingCategory | null) =>
    getRecentPriceDrops(sort, category),
);

// Keyed per-request dedup for the eyebrow's LATEST source — category only
// (sort deliberately absent: the value is sort-invariant by construction).
const latestDropCached = cache((category: ListingCategory | null) =>
  getLatestPriceDropAt(category),
);

function priceDropToProps(d: PriceDropListing) {
  // <ListingCard> derives the lead from listing fields; no explicit event prop
  // needed. priorPrice non-null → price-drop-new render; priorPrice null with
  // compareAtPrice slash → vendor-markdown render. No kind-disclosure either
  // way (canon: structural-not-visual).
  return { listing: d };
}

async function Eyebrow({
  sort,
  category,
}: {
  sort: ListingSort;
  category: ListingCategory | null;
}) {
  const [drops, latestEventAt] = await Promise.all([
    dropsCached(sort, category),
    latestDropCached(category),
  ]);

  if (drops.length === 0) {
    // Bare zero — eyebrow suppressed; the downtime fallback owns the surface.
    if (category === null) return null;
    // Filtered zero: qualified zero count + window chunk, freshness omitted —
    // the window chunk earns the slot at zero where the freshness chunk is
    // impossible.
    return (
      <PageEyebrow
        chunks={[
          `0 ${chromeCategoryLabel(category)} PRICE DROPS`,
          `LAST ${PRICE_DROP_WINDOW.toUpperCase()}`,
        ]}
      />
    );
  }

  // LATEST reads the dedicated cap=1 newest-ladder fetch, NOT the rendered
  // set: the wrapper cap truncates after the ladder sort, so under price sorts
  // max(rendered.observedAt) reads the capped slice, not the window. No
  // eyebrow change under sort; the category arg keeps filtered eyebrows
  // in-category-honest. Rendered-set fallback covers the fetch-race edge only
  // (drops non-empty here, so a null latest means the window emptied between
  // the two cached reads).
  const latestObservedAt =
    latestEventAt ?? latestTimestamp(drops, (d) => d.observedAt);
  const latestRelative = formatRelativeTime(latestObservedAt, new Date()).toUpperCase();
  const countNoun = pluralize(drops.length, 'PRICE DROP', 'PRICE DROPS');
  // Filtered eyebrows qualify the count chunk — the filtered page covers the
  // category, not the market; a bare count under a filter silently overclaims
  // (disclosure-symmetry rule). Sort changes order, not coverage — no eyebrow
  // change under sort.
  const countChunk =
    category === null
      ? `${drops.length} ${countNoun}`
      : `${drops.length} ${chromeCategoryLabel(category)} ${countNoun}`;
  return (
    <PageEyebrow
      chunks={[
        countChunk,
        `LAST ${PRICE_DROP_WINDOW.toUpperCase()}`,
        `LATEST ${latestRelative}`,
      ]}
    />
  );
}

async function PriceDropsFeed({
  sort,
  category,
}: {
  sort: ListingSort;
  category: ListingCategory | null;
}) {
  const drops = await dropsCached(sort, category);

  if (drops.length === 0) {
    // Filtered-empty line: a filter miss is an honest zero, not a coverage
    // gap — no I-voice second sentence, no promise. Category renders
    // prose-register via the formatTypeLabel three-class resolver. Bare-URL
    // zero keeps DOWNTIME_FALLBACK.
    if (category !== null) {
      return (
        <p role="status" className="text-base text-ink py-6">
          No {formatTypeLabel(category).display} price drops in the last{' '}
          {PRICE_DROP_WINDOW}.
        </p>
      );
    }
    return (
      <p role="status" className="text-base text-ink py-6">
        {DOWNTIME_FALLBACK}
      </p>
    );
  }

  // Time-bucket dividers are chrome over a recency-ordered list; under
  // price-asc / price-desc they would interleave nonsensically. Dividers
  // gate on the default sort — price-sorted feeds render flat.
  const withDividers = sort === 'newest';

  if (!withDividers || drops.length < DIVIDER_THRESHOLD) {
    return (
      <>
        {drops.map((d) => (
          // Bare id key — the union dedups to one row per listing.
          <ListingCard key={d.id} {...priceDropToProps(d)} />
        ))}
      </>
    );
  }

  const now = new Date();
  const out: ReactNode[] = [];
  buildBucketedRows(drops, (d) => d.observedAt, now).forEach(({ row, label }, i) => {
    if (label !== null) {
      out.push(<GroupDivider key={`div-${i}`} label={label} />);
    }
    out.push(<ListingCard key={row.id} {...priceDropToProps(row)} />);
  });
  return <>{out}</>;
}

function FeedSkeleton() {
  const fields = [
    { label: 'Price', value: '' },
    { label: 'Listed', value: '' },
  ];
  return (
    <div aria-busy="true">
      {Array.from({ length: SKELETON_ROW_COUNT }).map((_, i) => (
        <div key={i} className="py-6 border-b border-line">
          <DataRowSkeleton fields={fields} />
        </div>
      ))}
    </div>
  );
}

export default async function DealsPage({ searchParams }: PageProps) {
  const sp = await searchParams;
  const sort = parseSort(sp.sort);
  const category = parseCategory(sp.category);

  return (
    <section className="px-6 py-12 max-w-3xl mx-auto">
      <Suspense fallback={<PageEyebrowSkeleton />}>
        <Eyebrow sort={sort} category={category} />
      </Suspense>
      <PageH1 className="mb-8">
        Price drops.
      </PageH1>
      {/* Two axes only — no INCLUDE OUT OF STOCK on feed surfaces
          (includeOOS omitted → axis not rendered). */}
      <SortFilterBar
        basePath="/deals"
        sort={sort}
        category={category}
        ariaLabel="Sort and filter listings"
      />
      <Suspense fallback={<FeedSkeleton />}>
        <PriceDropsFeed sort={sort} category={category} />
      </Suspense>
    </section>
  );
}
