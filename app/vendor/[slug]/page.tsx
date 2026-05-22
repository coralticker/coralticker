// Retired vendors (vendor.active === false) short-circuit before any inventory
// query — row stays in `vendors` per architecture-v1.md §1.3 row-retention rule
// but the page renders a back-link instead of inventory.
//
// Auction listings (currentPrice = null) reach <VendorInventoryRow> and render
// "price on request" per project_auctions_in_scope.md.

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
  type ListingCategory,
  type ListingSort,
} from '@/lib/queries/listings';
import { getLatestScrapeFinishedAt } from '@/lib/queries/scraper-runs';
import { DataRowSkeleton } from '@/components/ui/data-row-skeleton';
import { PageEyebrow } from '@/components/ui/page-eyebrow';
import { formatRelativeTime } from '@/lib/format/relative-time';
import { VendorInventoryRow } from './_components/vendor-inventory-row';
import { PaginationNav } from './_components/pagination-nav';
import { SortFilterBar } from './_components/sort-filter-bar';

export const revalidate = 600;

interface PageProps {
  params: Promise<{ slug: string }>;
  searchParams: Promise<{
    page?: string;
    sort?: string;
    category?: string;
    'in-stock'?: string;
  }>;
}

function parsePage(raw: string | undefined): number {
  if (!raw) return 1;
  const n = parseInt(raw, 10);
  if (Number.isNaN(n) || n < 1) return 1;
  return n;
}

const SORT_ALLOWLIST: readonly ListingSort[] = [
  'newest',
  'price-asc',
  'price-desc',
];
function parseSort(raw: string | undefined): ListingSort {
  if (!raw) return 'newest';
  return (SORT_ALLOWLIST as readonly string[]).includes(raw)
    ? (raw as ListingSort)
    : 'newest';
}

// Schema enum has 12 values; fish / invert / equipment / other are excluded
// from the filter UI and silently fall back to null here.
const CATEGORY_ALLOWLIST: readonly ListingCategory[] = [
  'sps',
  'lps',
  'softie',
  'zoa',
  'mushroom',
  'chalice',
  'anemone',
  'clam',
];
function parseCategory(raw: string | undefined): ListingCategory | null {
  if (!raw) return null;
  return (CATEGORY_ALLOWLIST as readonly string[]).includes(raw)
    ? (raw as ListingCategory)
    : null;
}

function parseInStock(raw: string | undefined): boolean {
  return raw === '1';
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
  // Canonical = bare route (no ?page query); paginated pages still resolve to
  // the bare-route SERP card. <link rel="prev"/"next"> emitted from the page
  // body via React 19 link hoisting (Next.js Metadata API has no first-class
  // prev/next slot).
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

async function Inventory({
  vendor,
  page,
  sort,
  category,
  inStock,
}: {
  vendor: Vendor;
  page: number;
  sort: ListingSort;
  category: ListingCategory | null;
  inStock: boolean;
}) {
  const listings = await getVendorInventory(
    vendor.id,
    page,
    sort,
    category,
    inStock,
  );

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
        <div key={i} className="py-6 border-b border-ink/30">
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
  //
  // CTK-053: sort/category/in-stock params parsed against allowlists; invalid
  // inputs silently default. Total query uses filter params (page-count
  // shrinks under filter); inventory query uses all four (page + sort +
  // filters).
  const sort = parseSort(sp.sort);
  const category = parseCategory(sp.category);
  const inStock = parseInStock(sp['in-stock']);
  const rawPage = parsePage(sp.page);
  const [total, latestScrapeAt] = await Promise.all([
    getVendorInventoryTotal(vendor.id, category, inStock),
    getLatestScrapeFinishedAt(vendor.id),
  ]);
  const totalPages = Math.max(1, Math.ceil(total / 50));
  const page = Math.min(rawPage, totalPages);

  // Empty branch (total === 0): eyebrow suppressed pending /brand-manager
  // empty-state register call; until then the empty-state body line below owns
  // the surface alone.
  const eyebrowChunks =
    total > 0
      ? latestScrapeAt !== null
        ? [
            `${total} ${total === 1 ? 'CORAL' : 'CORALS'}`,
            `UPDATED ${formatRelativeTime(latestScrapeAt, new Date()).toUpperCase()}`,
          ]
        : [`${total} ${total === 1 ? 'CORAL' : 'CORALS'}`]
      : null;

  // <link rel="prev"/"next"> emitted via React 19 link hoisting (auto-promoted
  // to document head when rendered without a `precedence` attribute). Next.js
  // Metadata API has no first-class prev/next slot; icons.other is the
  // documented escape hatch but semantically misleading.
  // Prev for page 2 routes to bare URL (canonical) per site.md §6 SEO discipline.
  // CTK-053: filter/sort params preserved in prev/next hrefs so SEO chain
  // stays within the filtered subset.
  function pageHref(p: number): string {
    const params = new URLSearchParams();
    if (sort !== 'newest') params.set('sort', sort);
    if (category !== null) params.set('category', category);
    if (inStock) params.set('in-stock', '1');
    if (p !== 1) params.set('page', String(p));
    const qs = params.toString();
    return qs ? `/vendor/${slug}?${qs}` : `/vendor/${slug}`;
  }
  const prevHref = pageHref(page - 1);
  const nextHref = pageHref(page + 1);

  return (
    <main className="px-6 py-12 max-w-3xl mx-auto">
      {page > 1 && <link rel="prev" href={prevHref} />}
      {page < totalPages && <link rel="next" href={nextHref} />}
      {eyebrowChunks && <PageEyebrow chunks={eyebrowChunks} />}
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
        <SortFilterBar
          slug={slug}
          sort={sort}
          category={category}
          inStock={inStock}
        />
        <h2 className="text-sm font-bold pb-2 mb-2 border-b border-ink/20">
          Current inventory.
        </h2>
        <Suspense fallback={<VendorInventorySkeleton />}>
          <Inventory
            vendor={vendor}
            page={page}
            sort={sort}
            category={category}
            inStock={inStock}
          />
        </Suspense>
        <PaginationNav
          currentPage={page}
          totalPages={totalPages}
          slug={slug}
          sort={sort}
          category={category}
          inStock={inStock}
        />
      </div>
    </main>
  );
}
