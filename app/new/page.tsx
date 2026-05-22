// /new — recent arrivals feed per site.md §4.4
//
// Server Component composing the page H1 + Suspense-wrapped feed of
// <ListingCard> per row + <GroupDivider> at day-bucket transitions
// (12-card threshold gate per branding-guide.md §"Group dividers" line 257).
// Data via getRecentArrivals() — UNION two-arm CTE specced at site.md §4.4
// lines 1240-1293, executed as the get_recent_arrivals() RPC per
// supabase/migrations/0007. Both `just-listed` and `back-in-stock` events
// fan through <ListingCard> via the rowToProps() discriminator-as-seam per
// Decision H + §4.4 lines 1316-1322.
//
// Empty-state per §4.4 row 1365: system-health anomaly (zero arrivals across
// all four Phase 1 vendors in 24h is a scraper-silence signal, not a real
// product state); renders downtime fallback adapted from branding-guide.md
// §"Downtime / error copy". Page H1 still renders.
//
// Loading-state: RSC Suspense fallback covers card placeholders only via
// <DataRowSkeleton fields={...}>; <GroupDivider> renders post-Suspense per
// §4.4 row 1366. Page H1 + outer layout resolve immediately.
//
// Error-state: route-level app/error.tsx boundary (Session 1b) covers throws.
//
// ISR revalidate=300 per §1.2 + §4.4 line 1303 (5 min ≤ scrape-completion
// target). Metadata wording verbatim from site.md §6.1 vocabulary.
//
// CTK-070: per-page eyebrow `N ARRIVALS · LATEST X AGO` renders ABOVE H1
// per branding-guide.md L220 + site.md §4.4 step 1. Empty-branch suppresses
// the eyebrow entirely per Decision Q (no source for LATEST). Eyebrow paints
// in its own Suspense; H1 + outer layout resolve immediately per §4.4
// Loading row. React.cache() dedupes the arrivals query across the eyebrow
// + feed Suspense boundaries (single derivation page-level per Decision Q;
// the topmost card's Listed timestamp = eyebrow's LATEST value).

import type { Metadata } from 'next';
import { cache } from 'react';
import { Suspense, type ReactNode } from 'react';
import { ListingCard } from '@/components/listing-card';
import { GroupDivider } from '@/components/group-divider';
import { DataRowSkeleton } from '@/components/ui/data-row-skeleton';
import { bucketLabel, bucketTransition } from '@/lib/format/group-bucket';
import { formatRelativeTime } from '@/lib/format/relative-time';
import {
  getRecentArrivals,
  type ArrivalListing,
  type Listing,
} from '@/lib/queries/listings';

export const revalidate = 300;

export const metadata: Metadata = {
  title: 'New coral arrivals — last 24 hours — CoralTicker',
  description:
    'New coral arrivals across reef vendors in the last 24 hours — just-listed and back-in-stock. One feed, every vendor.',
};

const DIVIDER_THRESHOLD = 12;

const DOWNTIME_FALLBACK =
  'Scrapers are catching up. New arrivals will surface here when they land.';

// Request-scoped dedup so the eyebrow + feed Suspense boundaries share one
// query roundtrip (single-derivation discipline per site.md Decision Q).
const arrivalsCached = cache(() => getRecentArrivals());

// Discriminator-as-seam per Decision H + §4.4 lines 1316-1322. View code
// converts a query row to <ListingCard> props; no per-view conditional inside
// the composition dispatches on event.
function rowToProps(arrival: ArrivalListing) {
  const { event, eventAt, ...listingFields } = arrival;
  const listing: Listing = listingFields;
  return event === 'just-listed'
    ? ({ listing, event: 'just-listed' } as const)
    : ({ listing, event: 'back-in-stock', observedAt: eventAt } as const);
}

async function Eyebrow() {
  const arrivals = await arrivalsCached();
  if (arrivals.length === 0) return null; // empty-branch suppresses eyebrow per Decision Q.
  const latestEventAt = arrivals[0]!.eventAt; // arrivals ordered DESC; first row is max(eventAt).
  const latestRelative = formatRelativeTime(latestEventAt, new Date()).toUpperCase();
  const countNoun = arrivals.length === 1 ? 'ARRIVAL' : 'ARRIVALS';
  return (
    <p className="text-xs uppercase tracking-[0.08em] font-mono text-ink mb-4">
      {arrivals.length} {countNoun}
      <span className="text-forest"> · </span>
      LATEST {latestRelative}
    </p>
  );
}

function EyebrowSkeleton() {
  return <div className="h-4 mb-4 bg-ink/5" aria-hidden="true" />;
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
    { label: 'Coral', value: '' },
    { label: 'Vendor', value: '' },
    { label: 'Price', value: '' },
    { label: 'Listed', value: '' },
  ];
  return (
    <div aria-busy="true">
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="py-6 border-b border-ink/10">
          <DataRowSkeleton fields={fields} />
        </div>
      ))}
    </div>
  );
}

export default function NewArrivalsPage() {
  return (
    <section className="px-6 py-12 max-w-3xl mx-auto">
      <Suspense fallback={<EyebrowSkeleton />}>
        <Eyebrow />
      </Suspense>
      <h1 className="text-3xl md:text-4xl font-bold mb-8">
        New arrivals · last 24 hours
      </h1>
      <Suspense fallback={<FeedSkeleton />}>
        <ArrivalsFeed />
      </Suspense>
    </section>
  );
}
