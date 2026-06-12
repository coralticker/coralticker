// getRecentDrops() is bounded to first_seen_at > now() - 7d, so the
// 'just-listed' fall-through is genuinely accurate — restock-then-relist
// listings with old first_seen_at no longer surface here. back-in-stock
// derivation lives at /new (the lead-event RPC has the data shape to
// distinguish first-seen vs. restock).

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
      <ul className="divide-y divide-line">
        {listings.map((listing) => (
          <li key={listing.id}>
            <ListingCard listing={listing} />
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
