import type { Metadata } from 'next';
import { cache } from 'react';
import { Suspense, type ReactNode } from 'react';
import { ListingCard } from '@/components/listing-card';
import { GroupDivider } from '@/components/group-divider';
import { DataRowSkeleton } from '@/components/ui/data-row-skeleton';
import { PageEyebrow, PageEyebrowSkeleton } from '@/components/ui/page-eyebrow';
import { bucketLabel, bucketTransition, DIVIDER_THRESHOLD } from '@/lib/format/group-bucket';
import { formatRelativeTime } from '@/lib/format/relative-time';
import { getRecentPriceDrops, type PriceDropListing } from '@/lib/queries/listings';

export const revalidate = 300;

export const metadata: Metadata = {
  title: 'Coral price drops — last 24 hours — CoralTicker',
  description:
    'Price drops across reef coral vendors in the last 24 hours. One feed, every vendor.',
};

const SKELETON_ROW_COUNT = 6;

const DOWNTIME_FALLBACK =
  "No price drops in the last 24 hours. I'll surface them as vendors update.";

const dropsCached = cache(() => getRecentPriceDrops());

function priceDropToProps(d: PriceDropListing) {
  return {
    listing: d,
    event: 'price-dropped' as const,
    priorPrice: d.priorPrice,
    observedAt: d.observedAt,
  };
}

async function Eyebrow() {
  const drops = await dropsCached();
  if (drops.length === 0) return null;
  const latestRelative = formatRelativeTime(drops[0]!.observedAt, new Date()).toUpperCase();
  const countNoun = drops.length === 1 ? 'PRICE DROP' : 'PRICE DROPS';
  return <PageEyebrow chunks={[`${drops.length} ${countNoun}`, `LATEST ${latestRelative}`]} />;
}

async function PriceDropsFeed() {
  const drops = await dropsCached();

  if (drops.length === 0) {
    return (
      <p role="status" className="text-base text-ink py-6">
        {DOWNTIME_FALLBACK}
      </p>
    );
  }

  if (drops.length < DIVIDER_THRESHOLD) {
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
    { label: 'Ref', value: '' },
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

export default function DealsPage() {
  return (
    <section className="px-6 py-12 max-w-3xl mx-auto">
      <Suspense fallback={<PageEyebrowSkeleton />}>
        <Eyebrow />
      </Suspense>
      <h1 className="text-3xl md:text-4xl font-bold mb-8">
        Price drops.
      </h1>
      <Suspense fallback={<FeedSkeleton />}>
        <PriceDropsFeed />
      </Suspense>
    </section>
  );
}
