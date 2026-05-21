// /vendors — flat alphabetical index of active vendors per CTK-055.
//
// Discovery surface for /vendor/[slug]; rows link directly into per-vendor
// inventory. Alphabetical sort by display_name per branding-guide.md L41-42
// (no curated tier ranking). v1-minimal: no enrichment, no eyebrow, no
// last-scrape timestamp (Phase 3 charter per CTK-009).
//
// ISR revalidate = 600 per site.md §1.2 + /vendor/[slug] precedent.

import type { Metadata } from 'next';
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

export default async function VendorsPage() {
  const vendors = await getAllActiveVendors();

  return (
    <main className="px-6 py-12 max-w-3xl mx-auto">
      <h1 className="text-3xl md:text-4xl font-bold mb-8">Vendors.</h1>
      <ul>
        {vendors.map((vendor) => (
          <li key={vendor.slug} className="py-3">
            <Link
              href={`/vendor/${vendor.slug}`}
              className="text-base font-bold underline"
            >
              {vendor.display_name}
            </Link>
          </li>
        ))}
      </ul>
    </main>
  );
}
