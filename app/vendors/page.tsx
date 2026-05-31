// /vendors — flat alphabetical index of active vendors per CTK-055.
//
// Discovery surface for /vendor/[slug]; rows link directly into per-vendor
// inventory. Alphabetical sort by display_name per branding-guide.md L41-42
// (no curated tier ranking). v1-minimal: no enrichment, no eyebrow, no
// last-scrape timestamp (Phase 3 charter per CTK-009).
//
// ISR revalidate = 600 per site.md §1.2 + /vendor/[slug] precedent.

import type { Metadata } from 'next';
import { Suspense } from 'react';
import Link from 'next/link';
import { getAllActiveVendors } from '@/lib/queries/vendors';

export const revalidate = 600;

export const metadata: Metadata = {
  title: 'Vendors — CoralTicker',
  description:
    'Every coral vendor on CoralTicker. Direct links to current inventory at each vendor.',
  alternates: {
    canonical: '/vendors',
  },
};

const SKELETON_ROW_COUNT = 6;

async function VendorList() {
  const vendors = await getAllActiveVendors();
  return (
    <ul>
      {vendors.map((vendor) => (
        <li
          key={vendor.slug}
          className="flex flex-wrap items-baseline gap-x-6 gap-y-1 py-3"
        >
          <Link
            href={`/vendor/${vendor.slug}`}
            className="text-base font-bold hover:underline focus-visible:underline underline-offset-[3px] decoration-1"
          >
            {vendor.display_name}
          </Link>
          <a
            href={vendor.base_url}
            target="_blank"
            rel="noopener noreferrer"
            className="hover:underline focus-visible:underline underline-offset-[3px] decoration-1"
          >
            Visit {vendor.display_name} &rarr;
          </a>
        </li>
      ))}
    </ul>
  );
}

function VendorListSkeleton() {
  return (
    <ul role="status" aria-busy="true" aria-label="Loading vendors">
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

export default function VendorsPage() {
  return (
    <main className="px-6 py-12 max-w-3xl mx-auto">
      <h1 className="text-3xl md:text-4xl font-bold mb-8">Vendors.</h1>
      <Suspense fallback={<VendorListSkeleton />}>
        <VendorList />
      </Suspense>
    </main>
  );
}
