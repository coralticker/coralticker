import type { Metadata } from 'next';
import { cache } from 'react';
import { Suspense, type ReactNode } from 'react';
import { ListingCard } from '@/components/listing-card';
import { GroupDivider } from '@/components/group-divider';
import { DataRowSkeleton } from '@/components/ui/data-row-skeleton';
import { PageEyebrow, PageEyebrowSkeleton } from '@/components/ui/page-eyebrow';
import { SortFilterBar } from '@/components/ui/sort-filter-bar';
import { bucketLabel, bucketTransition, DIVIDER_THRESHOLD } from '@/lib/format/group-bucket';
import { formatRelativeTime } from '@/lib/format/relative-time';
import { formatTypeLabel } from '@/lib/format/type-label';
import { parseCategory, parseSort } from '@/lib/queries/listing-params';
import {
  getRecentArrivals,
  type ArrivalListing,
  type ListingCategory,
  type ListingSort,
} from '@/lib/queries/listings';

// CTK-127: the searchParams read below flips this route dynamic at runtime
// (CTK-046/126 precedent); getRecentArrivals' unstable_cache wrap keyed on
// (sort, category) carries the 300s data cadence.
export const revalidate = 300;

export const metadata: Metadata = {
  title: 'New coral arrivals — CoralTicker',
  description:
    'New coral arrivals across reef vendors — just-listed and back-in-stock. One feed, every vendor.',
};

interface PageProps {
  searchParams: Promise<{ sort?: string; category?: string }>;
}

const SKELETON_ROW_COUNT = 6;

const DOWNTIME_FALLBACK =
  "No new arrivals in the last 24 hours. I'll surface them as vendors list.";

// CTK-127: arg-taking per the /review-plan cache() re-key pin — a no-arg
// wrapper would serve one cached shape for all filter states in a request
// tree; React cache() keys per-request dedup by the (sort, category) args.
const arrivalsCached = cache(
  (sort: ListingSort, category: ListingCategory | null) =>
    getRecentArrivals(sort, category),
);

function rowToProps(arrival: ArrivalListing) {
  const { event, ...listing } = arrival;
  // CTK-047 Session 5 — baseEvent carries the RPC's just-listed vs.
  // back-in-stock hint; <ListingCard> derives "price dropped at" itself from
  // listing.priorPrice + priceDropObservedAt + listing.compareAtPrice. The
  // 'price-dropped' RPC arm falls back to 'just-listed' baseEvent (composition
  // overrides via the derivation rule).
  const baseEvent = event === 'back-in-stock' ? 'back-in-stock' : 'just-listed';
  return { listing, baseEvent } as const;
}

// Chrome register is always ALL-CAPS regardless of type-label class
// (branding-guide §"Type label casing" chrome-inheritance) — all 8 filterable
// categories are single-word enum values, so the blanket transform is safe
// here; prose register below goes through formatTypeLabel instead.
function chromeCategoryLabel(category: ListingCategory): string {
  return category.toUpperCase();
}

async function Eyebrow({
  sort,
  category,
}: {
  sort: ListingSort;
  category: ListingCategory | null;
}) {
  const arrivals = await arrivalsCached(sort, category);

  if (arrivals.length === 0) {
    // Bare zero — eyebrow suppressed; the downtime fallback owns the surface.
    if (category === null) return null;
    // Filtered zero (branding-guide §"Eyebrow shape + slot" filtered-eyebrows
    // lock): qualified zero count + window chunk, freshness omitted — the
    // window chunk earns the slot at zero where the freshness chunk is
    // impossible.
    return (
      <PageEyebrow
        chunks={[`0 ${chromeCategoryLabel(category)} ARRIVALS`, 'LAST 24 HOURS']}
      />
    );
  }

  // LATEST = max(eventAt), not index 0 — price-sorted renders break the
  // recency-order assumption (/review-plan pin).
  const latestEventAt = arrivals.reduce(
    (max, a) =>
      new Date(a.eventAt).getTime() > new Date(max).getTime() ? a.eventAt : max,
    arrivals[0]!.eventAt,
  );
  const latestRelative = formatRelativeTime(latestEventAt, new Date()).toUpperCase();
  const countNoun = arrivals.length === 1 ? 'ARRIVAL' : 'ARRIVALS';
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
}: {
  sort: ListingSort;
  category: ListingCategory | null;
}) {
  const arrivals = await arrivalsCached(sort, category);

  if (arrivals.length === 0) {
    // Filtered-empty line (branding-guide §"Short-copy assets", CTK-127): a
    // filter miss is an honest zero, not a coverage gap — no I-voice second
    // sentence, no promise. Category renders prose-register via the
    // formatTypeLabel three-class resolver (SPS/LPS caps, Zoa/Clam Title
    // Case). Bare-URL zero keeps DOWNTIME_FALLBACK.
    if (category !== null) {
      return (
        <p role="status" className="text-base text-ink py-6">
          No {formatTypeLabel(category).display} arrivals in the last 24 hours.
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
  // gate on the default sort — price-sorted feeds render flat (CTK-127).
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
  for (let i = 0; i < arrivals.length; i++) {
    const curr = arrivals[i]!;
    const prev = i > 0 ? arrivals[i - 1]! : null;
    if (prev && bucketTransition(prev.eventAt, curr.eventAt)) {
      out.push(
        <GroupDivider key={`div-${i}`} label={bucketLabel(curr.eventAt, now)} />,
      );
    }
    out.push(<ListingCard key={curr.id} {...rowToProps(curr)} />);
  }
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
        <div key={i} className="py-6 border-b border-ink/30">
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

  return (
    <section className="px-6 py-12 max-w-3xl mx-auto">
      <Suspense fallback={<PageEyebrowSkeleton />}>
        <Eyebrow sort={sort} category={category} />
      </Suspense>
      <h1 className="text-3xl md:text-4xl font-bold mb-8">
        New arrivals.
      </h1>
      {/* Two axes only — no INCLUDE OUT OF STOCK on feed surfaces per
          branding-guide §"State markers" deal-buyer query-filter lock
          (includeOOS omitted → axis not rendered). */}
      <SortFilterBar basePath="/new" sort={sort} category={category} />
      <Suspense fallback={<FeedSkeleton />}>
        <ArrivalsFeed sort={sort} category={category} />
      </Suspense>
    </section>
  );
}
