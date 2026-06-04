// /corals — flat alphabetical index of named corals with at-least-one
// in-window listing per CTK-057. Composition mirrors /vendors (CTK-055):
// max-w-3xl frame, prose-register H1, Suspense + skeleton, py-3 rows.
//
// Dormancy gate: getAllNamedCoralsWithListings() restricts to corals whose
// 7-day last_seen_at window is populated — every rendered row routes to a
// populated /coral/[slug] (predicate parity with getCoralAvailability).
// v1-minimal: no enrichment, no eyebrow, no vendor counts (CTK-009 Phase 3
// charter). Single internal link per row — /coral/[slug] hero owns the
// vendor CTA, so no outbound pair (deviation from the /vendors two-link row
// is scope, not drift). Row underline treatment drift-added to the /vendors
// hover-only carve-out per /brand-manager 2026-06-04 (branding-guide §"Color
// system" carve-out entry).
//
// ISR revalidate = 600 per site.md §1.2 + /vendors precedent.

import type { Metadata } from 'next';
import { Suspense } from 'react';
import Link from 'next/link';
import { getAllNamedCoralsWithListings } from '@/lib/queries/named-corals';

export const revalidate = 600;

export const metadata: Metadata = {
  title: 'Corals — CoralTicker',
  description:
    'Named corals recently listed across the vendors CoralTicker tracks. Direct links to availability.',
  alternates: {
    canonical: '/corals',
  },
};

const SKELETON_ROW_COUNT = 6;

// Defensive zero-row branch — fires only if none of the seeded corals has an
// in-window listing. Copy locked /brand-manager 2026-06-04 (gap-moment
// "I"-voice carve-out). The "7 days" literal is in PARITY with
// CORAL_RECENCY_DAYS = 7 (lib/queries/listings.ts:25) and the interval in
// getAllNamedCoralsWithListings — if the window moves, this copy moves too.
const EMPTY_FALLBACK =
  "No named corals listed in the last 7 days. When one lists, I'll surface it here.";

async function CoralList() {
  const corals = await getAllNamedCoralsWithListings();

  if (corals.length === 0) {
    return (
      <p role="status" className="text-base text-ink py-6">
        {EMPTY_FALLBACK}
      </p>
    );
  }

  return (
    <ul>
      {corals.map((coral) => (
        <li key={coral.slug} className="py-3">
          <Link
            href={`/coral/${coral.slug}`}
            className="text-base font-bold hover:underline focus-visible:underline underline-offset-[3px] decoration-1"
          >
            {coral.canonical_name}
          </Link>
        </li>
      ))}
    </ul>
  );
}

function CoralListSkeleton() {
  return (
    <ul role="status" aria-busy="true" aria-label="Loading corals">
      {Array.from({ length: SKELETON_ROW_COUNT }).map((_, i) => (
        <li key={i} className="py-3">
          <span
            aria-hidden="true"
            className="inline-block h-4 w-40 align-middle bg-ink/15 rounded-sm animate-pulse"
          />
        </li>
      ))}
    </ul>
  );
}

export default function CoralsPage() {
  return (
    <main className="px-6 py-12 max-w-3xl mx-auto">
      <h1 className="text-3xl md:text-4xl font-bold mb-8">Corals.</h1>
      <Suspense fallback={<CoralListSkeleton />}>
        <CoralList />
      </Suspense>
    </main>
  );
}
