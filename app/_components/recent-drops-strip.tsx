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
// Event derivation: v1 default hardcodes event='just-listed' for every strip
// card per §4.2 event-derivation rule. CTK-080 bound getRecentDrops() to
// first_seen_at > now() - 7d (lib/queries/listings.ts), so the hardcode is
// now genuinely accurate — restock-then-relist listings with old
// first_seen_at no longer surface here. Per-listing event-type derivation
// still lives in /new + /deals which have the data shape (UNION two-arm CTE
// / LAG window) to distinguish just-listed vs. back-in-stock vs.
// price-dropped.
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

export function RecentDropsStrip({
  listings,
  cta = DEFAULT_CTA,
}: RecentDropsStripProps) {
  return (
    <section className="px-6 py-8 max-w-3xl mx-auto">
      <ul className="divide-y divide-ink/10">
        {listings.map((listing) => (
          <li key={listing.id}>
            <ListingCard listing={listing} event="just-listed" />
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
