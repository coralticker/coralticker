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
  const { event, ...listing } = arrival;
  // CTK-047 Session 5 — baseEvent carries the RPC's just-listed vs.
  // back-in-stock hint; <ListingCard> derives "price dropped at" itself from
  // listing.priorPrice + priceDropObservedAt + listing.compareAtPrice. The
  // 'price-dropped' RPC arm falls back to 'just-listed' baseEvent (composition
  // overrides via the derivation rule).
  const baseEvent = event === 'back-in-stock' ? 'back-in-stock' : 'just-listed';
  return { listing, baseEvent } as const;
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
