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
  getRecentPriceDrops,
  type ListingCategory,
  type ListingSort,
  type PriceDropListing,
} from '@/lib/queries/listings';

// CTK-127: the searchParams read below flips this route dynamic at runtime
// (CTK-046/126 precedent); getRecentPriceDrops' unstable_cache wrap keyed on
// (sort, category) carries the 300s data cadence.
export const revalidate = 300;

export const metadata: Metadata = {
  title: 'Coral price drops — CoralTicker',
  description:
    'Price drops across reef coral vendors. One feed, every vendor.',
};

interface PageProps {
  searchParams: Promise<{ sort?: string; category?: string }>;
}

const SKELETON_ROW_COUNT = 6;

// /deals query-window value — one constant, three consumers (downtime
// fallback, filtered-empty line, filtered-zero eyebrow window chunk) per the
// CTK-124 Q-1 eyebrow lock (branding-guide §"Eyebrow shape + slot"). Tracks
// the get_recent_price_drops() LAG-window cap (24h per migration 0009);
// CTK-124 D-1 moves the window to 7 days with the union-scope RPC — update
// this constant and the SQL together so window drift stays grep-able.
const PRICE_DROP_WINDOW = '24 hours';

const DOWNTIME_FALLBACK = `No price drops in the last ${PRICE_DROP_WINDOW}. I'll surface them as vendors update.`;

// CTK-127: arg-taking per the /review-plan cache() re-key pin — a no-arg
// wrapper would serve one cached shape for all filter states in a request
// tree; React cache() keys per-request dedup by the (sort, category) args.
const dropsCached = cache(
  (sort: ListingSort, category: ListingCategory | null) =>
    getRecentPriceDrops(sort, category),
);

function priceDropToProps(d: PriceDropListing) {
  // CTK-047 Session 5 — <ListingCard> derives "price dropped at" from
  // listing.priorPrice (non-null on every PriceDropListing row by the
  // get_recent_price_drops() RPC contract). No explicit event prop needed.
  return { listing: d };
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
  const drops = await dropsCached(sort, category);

  if (drops.length === 0) {
    // Bare zero — eyebrow suppressed; the downtime fallback owns the surface.
    if (category === null) return null;
    // Filtered zero (branding-guide §"Eyebrow shape + slot" filtered-eyebrows
    // lock): qualified zero count + window chunk, freshness omitted — the
    // window chunk earns the slot at zero where the freshness chunk is
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

  // LATEST = max(observedAt), not index 0 — price-sorted renders break the
  // recency-order assumption (/review-plan pin).
  const latestObservedAt = drops.reduce(
    (max, d) =>
      new Date(d.observedAt).getTime() > new Date(max).getTime()
        ? d.observedAt
        : max,
    drops[0]!.observedAt,
  );
  const latestRelative = formatRelativeTime(latestObservedAt, new Date()).toUpperCase();
  const countNoun = drops.length === 1 ? 'PRICE DROP' : 'PRICE DROPS';
  // Filtered eyebrows qualify the count chunk — the filtered page covers the
  // category, not the market; a bare count under a filter silently overclaims
  // (disclosure-symmetry rule). Sort changes order, not coverage — no eyebrow
  // change under sort.
  const countChunk =
    category === null
      ? `${drops.length} ${countNoun}`
      : `${drops.length} ${chromeCategoryLabel(category)} ${countNoun}`;
  return <PageEyebrow chunks={[countChunk, `LATEST ${latestRelative}`]} />;
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
    // Filtered-empty line (branding-guide §"Short-copy assets", CTK-127): a
    // filter miss is an honest zero, not a coverage gap — no I-voice second
    // sentence, no promise. Category renders prose-register via the
    // formatTypeLabel three-class resolver (SPS/LPS caps, Zoa/Clam Title
    // Case). Bare-URL zero keeps DOWNTIME_FALLBACK.
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
  // gate on the default sort — price-sorted feeds render flat (CTK-127).
  const withDividers = sort === 'newest';

  if (!withDividers || drops.length < DIVIDER_THRESHOLD) {
    return (
      <>
        {drops.map((d) => (
          <ListingCard key={d.id} {...priceDropToProps(d)} />
        ))}
      </>
    );
  }

  const now = new Date();
  const out: ReactNode[] = [];
  for (let i = 0; i < drops.length; i++) {
    const curr = drops[i]!;
    const prev = i > 0 ? drops[i - 1]! : null;
    if (prev && bucketTransition(prev.observedAt, curr.observedAt)) {
      out.push(
        <GroupDivider
          key={`div-${i}`}
          label={bucketLabel(curr.observedAt, now)}
        />,
      );
    }
    out.push(<ListingCard key={curr.id} {...priceDropToProps(curr)} />);
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

export default async function DealsPage({ searchParams }: PageProps) {
  const sp = await searchParams;
  const sort = parseSort(sp.sort);
  const category = parseCategory(sp.category);

  return (
    <section className="px-6 py-12 max-w-3xl mx-auto">
      <Suspense fallback={<PageEyebrowSkeleton />}>
        <Eyebrow sort={sort} category={category} />
      </Suspense>
      <h1 className="text-3xl md:text-4xl font-bold mb-8">
        Price drops.
      </h1>
      {/* Two axes only — no INCLUDE OUT OF STOCK on feed surfaces per
          branding-guide §"State markers" deal-buyer query-filter lock
          (includeOOS omitted → axis not rendered). */}
      <SortFilterBar basePath="/deals" sort={sort} category={category} />
      <Suspense fallback={<FeedSkeleton />}>
        <PriceDropsFeed sort={sort} category={category} />
      </Suspense>
    </section>
  );
}
