// /deals — current price-drop feed per site.md §4.3
//
// Server Component composing the page H1 + Suspense-wrapped feed of
// <ListingCard event="price-dropped" priorPrice observedAt /> per row.
// Data via getRecentPriceDrops() — LAG-window CTE specced at site.md §4.3
// lines 1135-1160, executed as the get_recent_price_drops() RPC per
// supabase/migrations/0008. priorPrice from LAG.prior_price flows into
// <ListingCard> + composes <DataRow value={{ kind: 'price-drop-new', ... }}>
// per Decision H (forest #1B5E20 + semantic <del> live inside the primitive).
// Listed-field timestamp = observed_at (price-drop observation time per
// site.md §4.3 lines 1176-1178 + listing-card.tsx:79-80 discriminator seam),
// not first_seen_at.
//
// Empty-state per §4.3 row 1214: quiet drop days are a REAL product state at
// v1 vendor count, not a system-health anomaly (contrast §4.4 /new's empty
// where zero arrivals across 4 vendors IS a scraper-silence signal). Page H1
// still renders. CTK-049 S1: gap-moment "I" voice per branding-guide.md
// L100-106 carve-out — /deals empty is structurally identical to /coral/[slug]
// empty per L103 example list ("the data slot ... the user expected is absent").
//
// Loading-state: RSC Suspense fallback covers card placeholders only via
// <DataRowSkeleton fields={...}>; <GroupDivider> renders post-Suspense per
// §4.3 group-divider applicability subsection (§4.4 owns composition shape
// via Q-J/Decision I; §4.3 inherits trigger only). Page H1 + outer layout
// resolve immediately.
//
// Error-state: route-level app/error.tsx boundary (Session 1b) covers throws.
//
// ISR revalidate=300 per §1.2 + §4.3 line 1166 (5 min ≤ scrape-completion
// target). Metadata wording verbatim from site.md §6.1 vocabulary.
//
// Q-J inheritance from §4.4: <GroupDivider> fires only when card array length
// is ≥ 12 AND observed_at distribution crosses a UTC day boundary. At v1
// scrape volume + 24h window + price-drop sparsity, the 12-card threshold is
// unlikely to trip on /deals — site.md §4.3 line 1191 calls this out. Logic
// is identical to /new for production-data-driven exercise per directive.

import type { Metadata } from 'next';
import { Suspense, type ReactNode } from 'react';
import { ListingCard } from '@/components/listing-card';
import { GroupDivider } from '@/components/group-divider';
import { DataRowSkeleton } from '@/components/ui/data-row-skeleton';
import { bucketLabel, bucketTransition } from '@/lib/format/group-bucket';
import { getRecentPriceDrops } from '@/lib/queries/listings';

export const revalidate = 300;

export const metadata: Metadata = {
  title: 'Coral price drops — last 24 hours — CoralTicker',
  description:
    'Price drops across reef coral vendors in the last 24 hours. One feed, every vendor.',
};

const DIVIDER_THRESHOLD = 12;

async function PriceDropsFeed() {
  const drops = await getRecentPriceDrops();

  if (drops.length === 0) {
    return (
      <p role="status" className="text-base text-ink py-6">
        No price drops in the last 24 hours. I&apos;ll surface them as vendors update.
      </p>
    );
  }

  if (drops.length < DIVIDER_THRESHOLD) {
    return (
      <>
        {drops.map((d) => (
          <ListingCard
            key={d.id}
            listing={d}
            event="price-dropped"
            priorPrice={d.priorPrice}
            observedAt={d.observedAt}
          />
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
    out.push(
      <ListingCard
        key={curr.id}
        listing={curr}
        event="price-dropped"
        priorPrice={curr.priorPrice}
        observedAt={curr.observedAt}
      />,
    );
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
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="py-6 border-b border-ink/10">
          <DataRowSkeleton fields={fields} />
        </div>
      ))}
    </div>
  );
}

export default function DealsPage() {
  return (
    <section className="px-6 py-12 max-w-3xl mx-auto">
      <h1 className="text-3xl md:text-4xl font-bold mb-8">
        Price drops · last 24 hours
      </h1>
      <Suspense fallback={<FeedSkeleton />}>
        <PriceDropsFeed />
      </Suspense>
    </section>
  );
}
