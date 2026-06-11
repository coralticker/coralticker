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
import {
  parseCategory,
  parseIncludeOOS,
  parseSort,
} from '@/lib/queries/listing-params';
import { getLatestScrapeFinishedAt } from '@/lib/queries/scraper-runs';
import { DataRowSkeleton } from '@/components/ui/data-row-skeleton';
import { PageEyebrow } from '@/components/ui/page-eyebrow';
import { PageShell } from '@/components/ui/page-shell';
import { SortFilterBar } from '@/components/ui/sort-filter-bar';
import { PageH1 } from '@/components/ui/page-h1';
import { SectionHeader } from '@/components/ui/section-header';
import { formatRelativeTime } from '@/lib/format/relative-time';
import { pluralize } from '@/lib/format/pluralize';
import { VendorInventoryRow } from './_components/vendor-inventory-row';
import { PaginationNav } from './_components/pagination-nav';

// CTK-047 B-2 cascade — medal-bearing surface; cadence equalized to 5min per
// /lead-architect re-disposition 2026-06-02. The real cadence lives in
// getVendorInventory's unstable_cache (300, lib/queries/listings.ts): the
// searchParams await makes this route fully dynamic — no static HTML is
// emitted for its paths despite generateStaticParams (prerender-manifest
// check, CTK-128 close review) — so the const below is inert for serving
// today; kept so the cadence intent survives if the route ever regains
// static prerendering. /vendors index (no medal) is unaffected.
export const revalidate = 300;

interface PageProps {
  params: Promise<{ slug: string }>;
  searchParams: Promise<{
    page?: string;
    sort?: string;
    category?: string;
    'include-oos'?: string;
  }>;
}

function parsePage(raw: string | undefined): number {
  if (!raw) return 1;
  const n = parseInt(raw, 10);
  if (Number.isNaN(n) || n < 1) return 1;
  return n;
}

// Sort / category / include-oos parsers moved to lib/queries/listing-params.ts
// at CTK-127 (three consumer routes post-promotion); parsePage stays local —
// pagination is a /vendor/[slug]-only axis.

export async function generateStaticParams(): Promise<{ slug: string }[]> {
  return getAllActiveVendorSlugs();
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { slug } = await params;
  const vendor = await getVendorBySlug(slug);
  if (!vendor) {
    // 404 copy duplicated at ./not-found.tsx metadata export — edit both or
    // neither. This null-branch is RSC-flight-only (verified next@15.5.18);
    // not-found.tsx paints the rendered head and is the keeper if one ever goes.
    return {
      title: 'Vendor not found', // suffix via root title.template
      description: "That vendor isn't on CoralTicker yet.",
    };
  }
  // Canonical = bare route (no ?page query); paginated pages still resolve to
  // the bare-route SERP card. <link rel="prev"/"next"> emitted from the page
  // body via React 19 link hoisting (Next.js Metadata API has no first-class
  // prev/next slot).
  return {
    title: `${vendor.display_name} — coral inventory`, // suffix via root title.template
    description: `Current coral inventory at ${vendor.display_name} — listing count, pricing, recency. Cross-vendor drop alerts.`,
    alternates: {
      canonical: `/vendor/${slug}`,
    },
    openGraph: {
      url: `/vendor/${slug}`,
      siteName: 'CoralTicker',
      type: 'website',
      locale: 'en_US',
    },
    twitter: { card: 'summary' },
  };
}

// Not-found-shaped chrome kept INLINE rather than via <NotFoundShell>: this is
// a retired-vendor gap surface (vendor.active === false), distinct 404
// semantics with its own back-link target (/new, not /vendors), so it consumes
// <PageShell> with inline children instead of the 404 specialization. py-16
// drift normalized to py-12 by the shared chrome (CTK-077 /brand-manager
// Element 1).
function RetiredVendorView({ vendor }: { vendor: Vendor }) {
  return (
    <PageShell as="section">
      <PageH1 className="mb-6">
        {vendor.display_name}
      </PageH1>
      <p className="text-base leading-relaxed mb-8">
        I&apos;m not tracking them anymore.
      </p>
      <p className="text-base">
        <Link href="/new" className="underline">
          &larr; back to new arrivals
        </Link>
      </p>
    </PageShell>
  );
}

async function Inventory({
  vendor,
  page,
  sort,
  category,
  includeOOS,
}: {
  vendor: Vendor;
  page: number;
  sort: ListingSort;
  category: ListingCategory | null;
  includeOOS: boolean;
}) {
  const listings = await getVendorInventory(
    vendor.id,
    page,
    sort,
    category,
    includeOOS,
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
        <div key={i} className="py-6 border-b border-line">
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
  // filters). CTK-098 (2026-05-31): in-stock semantic flipped — default is
  // in-stock-only; ?include-oos=1 opt-in restores mixed render.
  const sort = parseSort(sp.sort);
  const category = parseCategory(sp.category);
  const includeOOS = parseIncludeOOS(sp['include-oos']);
  const rawPage = parsePage(sp.page);
  const [total, latestScrapeAt] = await Promise.all([
    getVendorInventoryTotal(vendor.id, category, includeOOS),
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
            `${total} ${pluralize(total, 'CORAL', 'CORALS')}`,
            `UPDATED ${formatRelativeTime(latestScrapeAt, new Date()).toUpperCase()}`,
          ]
        : [`${total} ${pluralize(total, 'CORAL', 'CORALS')}`]
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
    if (includeOOS) params.set('include-oos', '1');
    if (p !== 1) params.set('page', String(p));
    const qs = params.toString();
    return qs ? `/vendor/${slug}?${qs}` : `/vendor/${slug}`;
  }
  const prevHref = pageHref(page - 1);
  const nextHref = pageHref(page + 1);

  return (
    <PageShell as="article">
      {page > 1 && <link rel="prev" href={prevHref} />}
      {page < totalPages && <link rel="next" href={nextHref} />}
      {eyebrowChunks && <PageEyebrow chunks={eyebrowChunks} />}
      <PageH1 className="mb-4">
        {vendor.display_name}
      </PageH1>

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
          basePath={`/vendor/${slug}`}
          sort={sort}
          category={category}
          includeOOS={includeOOS}
        />
        <SectionHeader>
          Current inventory.
        </SectionHeader>
        <Suspense fallback={<VendorInventorySkeleton />}>
          <Inventory
            vendor={vendor}
            page={page}
            sort={sort}
            category={category}
            includeOOS={includeOOS}
          />
        </Suspense>
        <PaginationNav
          currentPage={page}
          totalPages={totalPages}
          slug={slug}
          sort={sort}
          category={category}
          includeOOS={includeOOS}
        />
      </div>
    </PageShell>
  );
}
