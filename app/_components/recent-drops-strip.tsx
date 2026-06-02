// §4.2 <RecentDropsStrip> — single-view co-located composition
//
// Demoted from site.md §3.5.3 2026-04-28 per Finding 1 — slated-growth claim
// ("Phase 4 per-vendor strips plausible") didn't pass Decision D's 3+-view
// inclusion bar. Lives at app/_components/ until a concrete second consumer
// surfaces (most plausible: CTK-016 daily-digest preview surface OR /about
// live-feed sample — neither committed today).
//
// Ordering applied by caller, not by the composition (Decision G #1 + Q-E).
// The homepage Server Component runs the query (ORDER BY first_seen_at DESC
// with dedup on named_coral_id LIMIT 10 per Q-E v1 default); this composition
// iterates the array as passed.
//
// Event derivation per CTK-047 B-4 lock 2026-06-02: per-row deriveEvent()
// inspects listing.priorPrice + priceDropObservedAt (populated upstream by
// getRecentDrops()'s LEFT JOIN against get_listing_drop_context()). Rows with
// a CT-observed price-drop in the 24h window surface as 'price-dropped'
// variants in the strip; others fall through to 'just-listed'. Cross-surface
// medal canon at branding-guide L232 — heterogeneous events across the 10
// cards are intentional (row-level state, not surface-level decoration).
//
// CTK-080 bounded getRecentDrops() to first_seen_at > now() - 7d, so the
// 'just-listed' fall-through is genuinely accurate — restock-then-relist
// listings with old first_seen_at no longer surface here. back-in-stock
// derivation still lives at /new (UNION two-arm CTE has the data shape to
// distinguish first-seen vs. restock).
//
// No empty-state slot, no children, no styling slot — content shape is closed
// per Decision E + Decision G #4. Empty-state semantics are view-level.

import Link from 'next/link';
import { ListingCard } from '@/components/listing-card';
import type { Listing } from '@/lib/queries/listings';

interface RecentDropsStripProps {
  listings: Listing[];
  cta?: { label: string; href: string };
}

const DEFAULT_CTA = { label: 'view full feed →', href: '/new' };

function deriveEvent(listing: Listing) {
  if (listing.priorPrice !== null && listing.priceDropObservedAt !== null) {
    return {
      event: 'price-dropped' as const,
      priorPrice: listing.priorPrice,
      observedAt: listing.priceDropObservedAt,
    };
  }
  return { event: 'just-listed' as const };
}

export function RecentDropsStrip({
  listings,
  cta = DEFAULT_CTA,
}: RecentDropsStripProps) {
  return (
    <section className="px-6 py-8 max-w-3xl mx-auto">
      <ul className="divide-y divide-ink/10">
        {listings.map((listing) => (
          <li key={listing.id}>
            <ListingCard listing={listing} {...deriveEvent(listing)} />
          </li>
        ))}
      </ul>
      <div className="mt-6">
        <Link
          href={cta.href}
          className="text-sm text-ink underline underline-offset-2 hover:no-underline"
        >
          {cta.label}
        </Link>
      </div>
    </section>
  );
}
