// Alphabetical sort by display_name — no curated tier ranking.

import type { Metadata } from 'next';
import { Suspense } from 'react';
import Link from 'next/link';
import { getAllActiveVendors } from '@/lib/queries/vendors';
import { PageShell } from '@/components/ui/page-shell';
import { PageH1 } from '@/components/ui/page-h1';

export const revalidate = 600;

export const metadata: Metadata = {
  title: 'Vendors', // suffix via root title.template
  description:
    'Every coral vendor on CoralTicker. Direct links to current inventory at each vendor.',
  alternates: {
    canonical: '/vendors',
  },
  openGraph: { url: '/vendors', siteName: 'CoralTicker', type: 'website', locale: 'en_US' },
  twitter: { card: 'summary' },
};

const SKELETON_ROW_COUNT = 6;

async function VendorList() {
  const vendors = await getAllActiveVendors();
  return (
    <ul>
      {vendors.map((vendor) => (
        <li
          key={vendor.slug}
          className="flex flex-wrap items-baseline gap-x-6 gap-y-1 py-6 border-b border-line"
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
        <li key={i} className="py-6 border-b border-line">
          <span
            aria-hidden="true"
            className="inline-block h-4 w-40 align-middle bg-wash rounded-sm animate-pulse"
          />
        </li>
      ))}
    </ul>
  );
}

export default function VendorsPage() {
  return (
    <PageShell as="section">
      <PageH1 className="mb-8">Vendors.</PageH1>
      <Suspense fallback={<VendorListSkeleton />}>
        <VendorList />
      </Suspense>
    </PageShell>
  );
}
