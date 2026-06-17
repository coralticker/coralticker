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
  parseWindow,
} from '@/lib/queries/listing-params';
import {
  getRecentArrivals,
  windowDurationLabel,
  type ArrivalListing,
  type ListingCategory,
  type ListingSort,
  type ListingWindow,
} from '@/lib/queries/listings';

// The searchParams read below flips this route dynamic at runtime;
// getRecentArrivals' unstable_cache wrap keyed on (sort, category) carries
// the 300s data cadence.
export const revalidate = 300;

export const metadata: Metadata = {
  title: 'New coral arrivals', // suffix via root title.template
  description:
    'New coral arrivals across reef vendors — just-listed and back-in-stock. One feed.',
  alternates: { canonical: '/new' },
  openGraph: { url: '/new', siteName: 'CoralTicker', type: 'website', locale: 'en_US' },
  twitter: { card: 'summary' },
};

interface PageProps {
  searchParams: Promise<{ sort?: string; category?: string; window?: string }>;
}

const SKELETON_ROW_COUNT = 6;

// Window copy derives from the active window via windowDurationLabel() (the same
// one-source record the query reads for its hour arg), so it tracks ?window=week
// and can't drift from the actual window. Day-view strings are byte-identical to
// the pre-CTK-169 hardcoded copy ("last 24 hours" / "LAST 24 HOURS").
const downtimeFallback = (window: ListingWindow) =>
  `No new arrivals in the last ${windowDurationLabel(window)}. I'll surface them as vendors list.`;

// Arg-taking is load-bearing: a no-arg wrapper would serve one cached shape
// for all filter states in a request tree; React cache() keys per-request
// dedup by the (sort, category, window) args.
const arrivalsCached = cache(
  (sort: ListingSort, category: ListingCategory | null, window: ListingWindow) =>
    getRecentArrivals(sort, category, window),
);

function rowToProps(arrival: ArrivalListing) {
  const { event, ...listing } = arrival;
  // baseEvent carries the RPC's just-listed vs. back-in-stock hint;
  // <ListingCard> derives "price dropped at" itself. The 'price-dropped' RPC
  // arm falls back to 'just-listed' baseEvent.
  const baseEvent = event === 'back-in-stock' ? 'back-in-stock' : 'just-listed';
  return { listing, baseEvent } as const;
}

async function Eyebrow({
  sort,
  category,
  window,
}: {
  sort: ListingSort;
  category: ListingCategory | null;
  window: ListingWindow;
}) {
  const arrivals = await arrivalsCached(sort, category, window);

  if (arrivals.length === 0) {
    // Bare zero — eyebrow suppressed; the downtime fallback owns the surface.
    if (category === null) return null;
    // Filtered zero: qualified zero count + window chunk, freshness omitted —
    // the window chunk earns the slot at zero where the freshness chunk is
    // impossible.
    return (
      <PageEyebrow
        chunks={[
          `0 ${chromeCategoryLabel(category)} ARRIVALS`,
          `LAST ${windowDurationLabel(window).toUpperCase()}`,
        ]}
      />
    );
  }

  // LATEST = max(eventAt), not index 0 — price-sorted renders break the
  // recency-order assumption.
  const latestEventAt = latestTimestamp(arrivals, (a) => a.eventAt);
  const latestRelative = formatRelativeTime(latestEventAt, new Date()).toUpperCase();
  const countNoun = pluralize(arrivals.length, 'ARRIVAL', 'ARRIVALS');
  // Filtered eyebrows qualify the count chunk — the filtered page covers the
  // category, not the market; a bare count under a filter silently overclaims
  // (disclosure-symmetry rule). Sort changes order, not coverage — no eyebrow
  // change under sort.
  const countChunk =
    category === null
      ? `${arrivals.length} ${countNoun}`
      : `${arrivals.length} ${chromeCategoryLabel(category)} ${countNoun}`;
  return <PageEyebrow chunks={[countChunk, `LATEST ${latestRelative}`]} />;
}

async function ArrivalsFeed({
  sort,
  category,
  window,
}: {
  sort: ListingSort;
  category: ListingCategory | null;
  window: ListingWindow;
}) {
  const arrivals = await arrivalsCached(sort, category, window);

  if (arrivals.length === 0) {
    // Filtered-empty line: a filter miss is an honest zero, not a coverage
    // gap — no I-voice second sentence, no promise. Category renders
    // prose-register via the formatTypeLabel three-class resolver. Bare-URL
    // zero keeps the downtime fallback.
    if (category !== null) {
      return (
        <p role="status" className="text-base text-ink py-6">
          No {formatTypeLabel(category).display} arrivals in the last{' '}
          {windowDurationLabel(window)}.
        </p>
      );
    }
    return (
      <p role="status" className="text-base text-ink py-6">
        {downtimeFallback(window)}
      </p>
    );
  }

  // Time-bucket dividers are chrome over a recency-ordered list; under
  // price-asc / price-desc they would interleave nonsensically. Dividers
  // gate on the default sort — price-sorted feeds render flat.
  const withDividers = sort === 'newest';

  if (!withDividers || arrivals.length < DIVIDER_THRESHOLD) {
    return (
      <>
        {arrivals.map((a) => (
          <ListingCard key={a.id} {...rowToProps(a)} />
        ))}
      </>
    );
  }

  const now = new Date();
  const out: ReactNode[] = [];
  buildBucketedRows(arrivals, (a) => a.eventAt, now).forEach(({ row, label }, i) => {
    if (label !== null) {
      out.push(<GroupDivider key={`div-${i}`} label={label} />);
    }
    out.push(<ListingCard key={row.id} {...rowToProps(row)} />);
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

export default async function NewArrivalsPage({ searchParams }: PageProps) {
  const sp = await searchParams;
  const sort = parseSort(sp.sort);
  const category = parseCategory(sp.category);
  const window = parseWindow(sp.window);

  return (
    <section className="px-6 py-12 max-w-3xl mx-auto">
      <Suspense fallback={<PageEyebrowSkeleton />}>
        <Eyebrow sort={sort} category={category} window={window} />
      </Suspense>
      <PageH1 className="mb-8">
        New arrivals.
      </PageH1>
      {/* Two axes only — no INCLUDE OUT OF STOCK on feed surfaces
          (includeOOS omitted → axis not rendered). window passed so sort/category
          clicks preserve ?window=week (CTK-169); /vendor + /deals omit it. */}
      <SortFilterBar
        basePath="/new"
        sort={sort}
        category={category}
        window={window}
        ariaLabel="Sort and filter listings"
      />
      <Suspense fallback={<FeedSkeleton />}>
        <ArrivalsFeed sort={sort} category={category} window={window} />
      </Suspense>
    </section>
  );
}
