// /vendor/[slug] — per-vendor inventory per site.md §4.5
//
// Server Component with two-render-branch logic:
//   - Active vendor (vendor.active !== false): page H1 + vendor-link + section
//     transition + Suspense-wrapped inventory list (or empty-state line).
//   - Retired vendor (vendor.active === false): page H1 + voice-aligned
//     "I'm not tracking them anymore." fallback + back-link. NO inventory
//     query — short-circuit. Row preserved per architecture-v1.md §1.3
//     row-retention rule.
//   - Slug missing from vendors table: notFound() → app/vendor/[slug]/not-found.tsx.
//
// generateStaticParams() returns active vendors.slug; retired vendors are
// excluded from prerender but still reachable at runtime via dynamicParams.
//
// Section transition is single-state ("Current inventory.") across populated +
// empty — NOT the state-dynamic flip used at /coral/[slug]'s "Currently
// available." / "Currently unavailable." pair. /brand-manager Session 6 lock.
//
// Auction listings (currentPrice = null) flow through to <VendorInventoryRow>
// and render "price on request" per project_auctions_in_scope.md — getVendorInventory()
// deliberately does NOT filter `current_price IS NOT NULL`.
//
// ISR revalidate = 600 per site.md §1.2 + §4.5 lock (10 min).
//
// Cite: architecture-v1.md §1.3 (vendors), §1.4 (vendor_listings), §1.7
// (named_corals LEFT JOIN); site.md §4.5; branding-guide.md lines 98, 122,
// 165, 207.

import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';
import { Suspense } from 'react';
import {
  getAllActiveVendorSlugs,
  getVendorBySlug,
  type Vendor,
} from '@/lib/queries/vendors';
import { getVendorInventory } from '@/lib/queries/listings';
import { DataRowSkeleton } from '@/components/ui/data-row-skeleton';
import { VendorInventoryRow } from './_components/vendor-inventory-row';

export const revalidate = 600;

interface PageProps {
  params: Promise<{ slug: string }>;
}

export async function generateStaticParams(): Promise<{ slug: string }[]> {
  return getAllActiveVendorSlugs();
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { slug } = await params;
  const vendor = await getVendorBySlug(slug);
  if (!vendor) {
    return {
      title: 'Vendor not found — CoralTicker',
      description: "That vendor isn't on CoralTicker yet.",
    };
  }
  // Metadata wording verbatim from site.md §6.1 line 1708.
  return {
    title: `${vendor.display_name} — coral inventory — CoralTicker`,
    description: `Current coral inventory at ${vendor.display_name} — listing count, pricing, recency. Cross-vendor drop alerts.`,
  };
}

function RetiredVendorView({ vendor }: { vendor: Vendor }) {
  return (
    <main className="max-w-3xl mx-auto px-6 py-16">
      <h1 className="text-3xl md:text-4xl font-bold mb-6">
        {vendor.display_name}
      </h1>
      <p className="text-base leading-relaxed mb-8">
        I&apos;m not tracking them anymore.
      </p>
      <p className="text-base">
        <Link href="/new" className="underline">
          &larr; back to new arrivals
        </Link>
      </p>
    </main>
  );
}

async function Inventory({ vendor }: { vendor: Vendor }) {
  const listings = await getVendorInventory(vendor.id);

  if (listings.length === 0) {
    return (
      <p role="status" className="text-base py-6">
        Nothing in stock from {vendor.display_name} right now. I&apos;ll surface
        listings when they return.
      </p>
    );
  }

  return (
    <div>
      {listings.map((listing) => (
        <VendorInventoryRow key={listing.id} listing={listing} />
      ))}
    </div>
  );
}

function VendorInventorySkeleton() {
  const fields = [
    { label: 'Coral', value: '' },
    { label: 'Price', value: '' },
    { label: 'Listed', value: '' },
  ];
  return (
    <div aria-busy="true">
      {Array.from({ length: 4 }).map((_, i) => (
        <div key={i} className="py-6 border-b border-ink/10">
          <DataRowSkeleton fields={fields} />
        </div>
      ))}
    </div>
  );
}

export default async function VendorPage({ params }: PageProps) {
  const { slug } = await params;
  const vendor = await getVendorBySlug(slug);
  if (!vendor) notFound();

  if (vendor.active === false) {
    return <RetiredVendorView vendor={vendor} />;
  }

  return (
    <main className="px-6 py-12 max-w-3xl mx-auto">
      <h1 className="text-3xl md:text-4xl font-bold mb-4">
        {vendor.display_name}
      </h1>

      <p className="text-base mb-2">
        <a
          href={vendor.base_url}
          target="_blank"
          rel="noopener noreferrer"
          className="underline"
        >
          Visit {vendor.display_name} &rarr;
        </a>
      </p>

      <div className="mt-10">
        <h2 className="text-sm font-bold pb-2 mb-2 border-b border-ink/20">
          Current inventory.
        </h2>
        <Suspense fallback={<VendorInventorySkeleton />}>
          <Inventory vendor={vendor} />
        </Suspense>
      </div>
    </main>
  );
}
