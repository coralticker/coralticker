import type { Metadata } from 'next';
import { cache } from 'react';
import { Suspense, type ReactNode } from 'react';
import { ListingCard } from '@/components/listing-card';
import { GroupDivider } from '@/components/group-divider';
import { DataRowSkeleton } from '@/components/ui/data-row-skeleton';
import { PageEyebrow, PageEyebrowSkeleton } from '@/components/ui/page-eyebrow';
import { bucketLabel, bucketTransition, DIVIDER_THRESHOLD } from '@/lib/format/group-bucket';
import { formatRelativeTime } from '@/lib/format/relative-time';
import {
  getRecentArrivals,
  type ArrivalListing,
  type Listing,
} from '@/lib/queries/listings';

export const revalidate = 300;

export const metadata: Metadata = {
  title: 'New coral arrivals — CoralTicker',
  description:
    'New coral arrivals across reef vendors — just-listed and back-in-stock. One feed, every vendor.',
};

const SKELETON_ROW_COUNT = 6;

const DOWNTIME_FALLBACK =
  "No new arrivals in the last 24 hours. I'll surface them as vendors list.";

const arrivalsCached = cache(() => getRecentArrivals());

function rowToProps(arrival: ArrivalListing) {
  const { event, eventAt, ...listingFields } = arrival;
  const listing: Listing = listingFields;
  if (event === 'just-listed') {
    return { listing, event: 'just-listed' } as const;
  }
  if (event === 'price-dropped') {
    // priorPrice non-null by RPC contract: get_listing_lead_event()'s
    // price-dropped arm projects prior_price from the LAG-window CTE and
    // only emits rows where new_price < prior_price. Defensive fallback
    // mirrors the strip's deriveEvent shape — if the contract drifts, the
    // card degrades to just-listed rather than crashing on null priorPrice.
    if (arrival.priorPrice !== null) {
      return {
        listing,
        event: 'price-dropped' as const,
        priorPrice: arrival.priorPrice,
        observedAt: eventAt,
      } as const;
    }
    return { listing, event: 'just-listed' } as const;
  }
  return { listing, event: 'back-in-stock', observedAt: eventAt } as const;
}

async function Eyebrow() {
  const arrivals = await arrivalsCached();
  if (arrivals.length === 0) return null;
  const latestRelative = formatRelativeTime(arrivals[0]!.eventAt, new Date()).toUpperCase();
  const countNoun = arrivals.length === 1 ? 'ARRIVAL' : 'ARRIVALS';
  return <PageEyebrow chunks={[`${arrivals.length} ${countNoun}`, `LATEST ${latestRelative}`]} />;
}

async function ArrivalsFeed() {
  const arrivals = await arrivalsCached();

  if (arrivals.length === 0) {
    return (
      <p role="status" className="text-base text-ink py-6">
        {DOWNTIME_FALLBACK}
      </p>
    );
  }

  if (arrivals.length < DIVIDER_THRESHOLD) {
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

export default function NewArrivalsPage() {
  return (
    <section className="px-6 py-12 max-w-3xl mx-auto">
      <Suspense fallback={<PageEyebrowSkeleton />}>
        <Eyebrow />
      </Suspense>
      <h1 className="text-3xl md:text-4xl font-bold mb-8">
        New arrivals.
      </h1>
      <Suspense fallback={<FeedSkeleton />}>
        <ArrivalsFeed />
      </Suspense>
    </section>
  );
}
