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
import {
  getVendorInventory,
  getVendorInventoryTotal,
} from '@/lib/queries/listings';
import { DataRowSkeleton } from '@/components/ui/data-row-skeleton';
import { VendorInventoryRow } from './_components/vendor-inventory-row';
import { PaginationNav } from './_components/pagination-nav';

export const revalidate = 600;

interface PageProps {
  params: Promise<{ slug: string }>;
  searchParams: Promise<{ page?: string }>;
}

// CTK-046: parse ?page=N URL-state. Default 1; clamp NaN / < 1 / non-integer
// inputs to 1. Upper-bound clamp happens at the view layer once totalPages
// is computed — keeps malformed-but-positive ?page=999 graceful (renders last
// page) without notFound() drama.
function parsePage(raw: string | undefined): number {
  if (!raw) return 1;
  const n = parseInt(raw, 10);
  if (Number.isNaN(n) || n < 1) return 1;
  return n;
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
  // CTK-046: canonical = bare route per site.md §6 (no ?page query); paginated
  // pages still resolve to the bare-route SERP card. <link rel="prev"/"next">
  // emitted from the page body via React 19 link hoisting (Next.js Metadata
  // API has no first-class prev/next slot).
  return {
    title: `${vendor.display_name} — coral inventory — CoralTicker`,
    description: `Current coral inventory at ${vendor.display_name} — listing count, pricing, recency. Cross-vendor drop alerts.`,
    alternates: {
      canonical: `/vendor/${slug}`,
    },
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

async function Inventory({ vendor, page }: { vendor: Vendor; page: number }) {
  const listings = await getVendorInventory(vendor.id, page);

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

export default async function VendorPage({ params, searchParams }: PageProps) {
  const { slug } = await params;
  const sp = await searchParams;
  const vendor = await getVendorBySlug(slug);
  if (!vendor) notFound();

  if (vendor.active === false) {
    return <RetiredVendorView vendor={vendor} />;
  }

  // CTK-046: page parse + totalPages math sequenced after vendor lookup so
  // retired / not-found vendors short-circuit before the count query fires.
  // Math.max(1, ...) holds the floor at 1 even on empty inventory — single-page
  // PaginationNav state still renders ("PAGE 1 OF 1" both-disabled), consistent
  // with brand-manager spec for /vendor/jf, /vendor/tsa, /vendor/pacific-east
  // v1 sparsity. Upper-clamp via Math.min keeps malformed ?page=999 graceful.
  const rawPage = parsePage(sp.page);
  const total = await getVendorInventoryTotal(vendor.id);
  const totalPages = Math.max(1, Math.ceil(total / 50));
  const page = Math.min(rawPage, totalPages);

  // <link rel="prev"/"next"> emitted via React 19 link hoisting (auto-promoted
  // to document head when rendered without a `precedence` attribute). Next.js
  // Metadata API has no first-class prev/next slot; icons.other is the
  // documented escape hatch but semantically misleading.
  // Prev for page 2 routes to bare URL (canonical) per site.md §6 SEO discipline.
  const prevHref =
    page === 2 ? `/vendor/${slug}` : `/vendor/${slug}?page=${page - 1}`;
  const nextHref = `/vendor/${slug}?page=${page + 1}`;

  return (
    <main className="px-6 py-12 max-w-3xl mx-auto">
      {page > 1 && <link rel="prev" href={prevHref} />}
      {page < totalPages && <link rel="next" href={nextHref} />}
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
          <Inventory vendor={vendor} page={page} />
        </Suspense>
        <PaginationNav currentPage={page} totalPages={totalPages} slug={slug} />
      </div>
    </main>
  );
}
