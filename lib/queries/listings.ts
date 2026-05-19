// lib/queries/listings.ts
//
// Server-side query helpers consumed by Phase 2 view Server Components.
// Listing shape mirrors site.md §3.5.1 — the read shape of architecture-v1.md
// §1.4 vendor_listings + joined named_corals + vendors.
//
// Five helpers per site.md §4 contracts:
//   getRecentDrops()        — homepage strip per §4.2 (plain JOIN + JS dedup)
//   getRecentPriceDrops()   — /deals LAG-window per §4.3 (RPC function 0008)
//   getRecentArrivals()     — /new UNION two-arm per §4.4 (RPC function 0007)
//   getCoralAvailability()  — /coral/[slug] per §4.1 (plain JOIN)
//   getVendorInventory()    — /vendor/[slug] per §4.5 (plain JOIN)
//
// Migrated CTK-043 cut-4 (2026-05-16) from supabase-js PostgREST builders to
// raw SQL via @neondatabase/serverless. Public types (Listing,
// PriceDropListing, ArrivalListing) and the Rpc*Row cast-site interfaces are
// preserved byte-for-byte — view components stay untouched.

import { unstable_cache } from 'next/cache';
import { getNeonSql } from '@/lib/db/neon';

export interface Listing {
  id: number;
  vendorSlug: string;
  vendorDisplayName: string;
  rawTitle: string;
  currentPrice: number | null;
  inStock: boolean;
  imageUrl: string | null;
  productUrl: string;
  firstSeenAt: string;
  matchConfidence: 'exact' | 'alias' | 'fuzzy' | 'manual' | null;
  namedCoralCanonicalName: string | null;
  namedCoralSlug: string | null;
  // Lineage fields per site.md §3.5.1 Lineage field rendering — only populated
  // when namedCoralCanonicalName is non-null (LEFT JOIN named_corals).
  namedCoralOriginVendor: string | null;
  namedCoralYearIntroduced: number | null;
}

// Flat row shape returned by the JOIN below. PostgREST's nested-relation
// shape (vendors: {...}, named_corals: {...}) is gone post-cut-4; columns
// flatten with vendor_/named_coral_ prefixes. year_introduced still omitted
// per Q-040-11 hold-position (hosted named_corals lacks the column per
// 2026-05-14 probe).
interface VendorListingRow {
  id: number;
  raw_title: string;
  current_price: number | string | null;
  in_stock: boolean;
  image_url: string | null;
  product_url: string;
  first_seen_at: string;
  match_confidence: 'exact' | 'alias' | 'fuzzy' | 'manual' | null;
  named_coral_id: number | null;
  vendor_slug: string;
  vendor_display_name: string;
  named_coral_canonical_name: string | null;
  named_coral_slug: string | null;
  named_coral_origin_vendor: string | null;
}

function rowToListing(row: VendorListingRow): Listing {
  return {
    id: row.id,
    vendorSlug: row.vendor_slug,
    vendorDisplayName: row.vendor_display_name,
    rawTitle: row.raw_title,
    currentPrice: row.current_price !== null ? Number(row.current_price) : null,
    inStock: row.in_stock,
    imageUrl: row.image_url,
    productUrl: row.product_url,
    firstSeenAt: row.first_seen_at,
    matchConfidence: row.match_confidence,
    namedCoralCanonicalName: row.named_coral_canonical_name,
    namedCoralSlug: row.named_coral_slug,
    namedCoralOriginVendor: row.named_coral_origin_vendor,
    namedCoralYearIntroduced: null,
  };
}

// Homepage strip per site.md §4.2 + Q-E default policy.
// Plain JOIN with LEFT JOIN named_corals; JS-side dedup on named_coral_id
// preserved from the Supabase impl (rather than pushing DISTINCT ON into SQL,
// which complicates the LIMIT semantics).
export async function getRecentDrops(limit = 10): Promise<Listing[]> {
  const sql = getNeonSql();
  const overFetch = limit * 3;
  const rows = (await sql`
    SELECT
      vl.id,
      vl.raw_title,
      vl.current_price,
      vl.in_stock,
      vl.image_url,
      vl.product_url,
      vl.first_seen_at,
      vl.match_confidence,
      vl.named_coral_id,
      v.slug AS vendor_slug,
      v.display_name AS vendor_display_name,
      nc.canonical_name AS named_coral_canonical_name,
      nc.slug AS named_coral_slug,
      nc.origin_vendor AS named_coral_origin_vendor
    FROM vendor_listings vl
    JOIN vendors v ON v.id = vl.vendor_id
    LEFT JOIN named_corals nc ON nc.id = vl.named_coral_id
    WHERE vl.in_stock = true
    ORDER BY vl.first_seen_at DESC
    LIMIT ${overFetch}
  `) as unknown as VendorListingRow[];

  const seen = new Set<number>();
  const out: Listing[] = [];
  for (const row of rows) {
    const dedupKey = row.named_coral_id;
    if (dedupKey !== null && seen.has(dedupKey)) continue;
    if (dedupKey !== null) seen.add(dedupKey);
    out.push(rowToListing(row));
    if (out.length >= limit) break;
  }
  return out;
}

// /coral/[slug] per site.md §4.1.
// Filtered by named_coral_id AND last_seen_at > now() - interval '7 days'.
export async function getCoralAvailability(namedCoralId: number): Promise<Listing[]> {
  const sql = getNeonSql();
  const sevenDaysAgo = new Date(Date.now() - 7 * 86_400_000).toISOString();

  const rows = (await sql`
    SELECT
      vl.id,
      vl.raw_title,
      vl.current_price,
      vl.in_stock,
      vl.image_url,
      vl.product_url,
      vl.first_seen_at,
      vl.match_confidence,
      vl.named_coral_id,
      v.slug AS vendor_slug,
      v.display_name AS vendor_display_name,
      nc.canonical_name AS named_coral_canonical_name,
      nc.slug AS named_coral_slug,
      nc.origin_vendor AS named_coral_origin_vendor
    FROM vendor_listings vl
    JOIN vendors v ON v.id = vl.vendor_id
    LEFT JOIN named_corals nc ON nc.id = vl.named_coral_id
    WHERE vl.named_coral_id = ${namedCoralId}
      AND vl.last_seen_at > ${sevenDaysAgo}
    ORDER BY vl.first_seen_at DESC
  `) as unknown as VendorListingRow[];

  return rows.map(rowToListing);
}

// /vendor/[slug] per site.md §4.5.
// Filtered by vendor_id AND last_seen_at > now() - interval '14 days'.
// CTK-046: paginated via LIMIT 50 OFFSET ((page - 1) * 50); default page = 1
// keeps non-paginated callers untouched. unstable_cache wrap (ISR-regression
// fold 2026-05-18): searchParams reading flipped the route pure-dynamic at
// runtime; cache key on (vendorId, page) restores ISR semantics per site.md
// §4.5 + §1.2 revalidate = 600. fourteenDaysAgo computed inside the cached
// fn — drifts up to 10 min within TTL window (mathematically acceptable on
// a 14-day window).
//
// CTK-053: sort + category + inStock params. Default sort 'newest' preserves
// the pre-CTK-053 ORDER BY first_seen_at DESC. price-asc / price-desc use
// NULLS LAST in both directions so "price on request" auction rows
// (current_price IS NULL per project_auctions_in_scope.md) sink below priced
// rows regardless of direction. Category = exact-match against the schema
// enum (architecture-v1.md §1.4 L360-362) — NULL silent in unfiltered state.
// In-stock toggle adds AND vl.in_stock = true when on. Cache key tuples
// extend per CTK-053 plan §Scope #8 — (vendorId, page, sort, category,
// inStock) avoids cross-filter bleed.

export type ListingSort = 'newest' | 'price-asc' | 'price-desc';

export type ListingCategory =
  | 'sps'
  | 'lps'
  | 'softie'
  | 'zoa'
  | 'mushroom'
  | 'chalice'
  | 'anemone'
  | 'clam';

export async function getVendorInventory(
  vendorId: number,
  page: number = 1,
  sort: ListingSort = 'newest',
  category: ListingCategory | null = null,
  inStock: boolean = false,
): Promise<Listing[]> {
  return unstable_cache(
    async () => {
      const sql = getNeonSql();
      const fourteenDaysAgo = new Date(Date.now() - 14 * 86_400_000).toISOString();
      const offset = (page - 1) * 50;

      // Optional filters collapse via SQL-side NULL/false constant folding:
      // `(${category}::text IS NULL OR vl.category = ${category})` lets a null
      // category short-circuit through the planner; same shape for inStock.
      // ORDER BY can't be parameterized — switch on the allowlisted sort
      // string and emit one of three full SQL queries. Sort is validated at
      // the view layer (page.tsx allowlist parse).
      const categoryParam = category ?? null;
      const inStockParam = inStock;

      const rows = (await (() => {
        if (sort === 'price-asc') {
          return sql`
            SELECT
              vl.id, vl.raw_title, vl.current_price, vl.in_stock,
              vl.image_url, vl.product_url, vl.first_seen_at,
              vl.match_confidence, vl.named_coral_id,
              v.slug AS vendor_slug, v.display_name AS vendor_display_name,
              nc.canonical_name AS named_coral_canonical_name,
              nc.slug AS named_coral_slug,
              nc.origin_vendor AS named_coral_origin_vendor
            FROM vendor_listings vl
            JOIN vendors v ON v.id = vl.vendor_id
            LEFT JOIN named_corals nc ON nc.id = vl.named_coral_id
            WHERE vl.vendor_id = ${vendorId}
              AND vl.last_seen_at > ${fourteenDaysAgo}
              AND (${categoryParam}::text IS NULL OR vl.category = ${categoryParam})
              AND (NOT ${inStockParam}::boolean OR vl.in_stock = true)
            ORDER BY vl.current_price ASC NULLS LAST, vl.first_seen_at DESC
            LIMIT 50 OFFSET ${offset}
          `;
        }
        if (sort === 'price-desc') {
          return sql`
            SELECT
              vl.id, vl.raw_title, vl.current_price, vl.in_stock,
              vl.image_url, vl.product_url, vl.first_seen_at,
              vl.match_confidence, vl.named_coral_id,
              v.slug AS vendor_slug, v.display_name AS vendor_display_name,
              nc.canonical_name AS named_coral_canonical_name,
              nc.slug AS named_coral_slug,
              nc.origin_vendor AS named_coral_origin_vendor
            FROM vendor_listings vl
            JOIN vendors v ON v.id = vl.vendor_id
            LEFT JOIN named_corals nc ON nc.id = vl.named_coral_id
            WHERE vl.vendor_id = ${vendorId}
              AND vl.last_seen_at > ${fourteenDaysAgo}
              AND (${categoryParam}::text IS NULL OR vl.category = ${categoryParam})
              AND (NOT ${inStockParam}::boolean OR vl.in_stock = true)
            ORDER BY vl.current_price DESC NULLS LAST, vl.first_seen_at DESC
            LIMIT 50 OFFSET ${offset}
          `;
        }
        // sort === 'newest'
        return sql`
          SELECT
            vl.id, vl.raw_title, vl.current_price, vl.in_stock,
            vl.image_url, vl.product_url, vl.first_seen_at,
            vl.match_confidence, vl.named_coral_id,
            v.slug AS vendor_slug, v.display_name AS vendor_display_name,
            nc.canonical_name AS named_coral_canonical_name,
            nc.slug AS named_coral_slug,
            nc.origin_vendor AS named_coral_origin_vendor
          FROM vendor_listings vl
          JOIN vendors v ON v.id = vl.vendor_id
          LEFT JOIN named_corals nc ON nc.id = vl.named_coral_id
          WHERE vl.vendor_id = ${vendorId}
            AND vl.last_seen_at > ${fourteenDaysAgo}
            AND (${categoryParam}::text IS NULL OR vl.category = ${categoryParam})
            AND (NOT ${inStockParam}::boolean OR vl.in_stock = true)
          ORDER BY vl.first_seen_at DESC
          LIMIT 50 OFFSET ${offset}
        `;
      })()) as unknown as VendorListingRow[];

      return rows.map(rowToListing);
    },
    [
      'getVendorInventory',
      String(vendorId),
      String(page),
      sort,
      category ?? '_',
      inStock ? '1' : '0',
    ],
    {
      revalidate: 600,
      tags: [
        `vendor-${vendorId}-page-${page}-${sort}-${category ?? '_'}-${inStock ? '1' : '0'}`,
      ],
    },
  )();
}

// /vendor/[slug] total-pages math per site.md §4.5 + CTK-046 + CTK-053.
// COUNT against the same 14-day in-stock-recency window as getVendorInventory().
// No JOINs — vendor_id + last_seen_at + optional category + optional in_stock
// drive the count; vendors / named_corals do not constrain row count.
// unstable_cache wrap per ISR-fold. Cache key drops sort + page (totals are
// invariant to both) — keeps cache footprint linear in category × inStock
// rather than category × inStock × page × sort.
export async function getVendorInventoryTotal(
  vendorId: number,
  category: ListingCategory | null = null,
  inStock: boolean = false,
): Promise<number> {
  return unstable_cache(
    async () => {
      const sql = getNeonSql();
      const fourteenDaysAgo = new Date(Date.now() - 14 * 86_400_000).toISOString();
      const categoryParam = category ?? null;
      const inStockParam = inStock;
      const rows = (await sql`
        SELECT COUNT(*) AS total
        FROM vendor_listings vl
        WHERE vl.vendor_id = ${vendorId}
          AND vl.last_seen_at > ${fourteenDaysAgo}
          AND (${categoryParam}::text IS NULL OR vl.category = ${categoryParam})
          AND (NOT ${inStockParam}::boolean OR vl.in_stock = true)
      `) as unknown as { total: number | string }[];
      const first = rows[0];
      return first ? Number(first.total) : 0;
    },
    [
      'getVendorInventoryTotal',
      String(vendorId),
      category ?? '_',
      inStock ? '1' : '0',
    ],
    {
      revalidate: 600,
      tags: [`vendor-${vendorId}-total-${category ?? '_'}-${inStock ? '1' : '0'}`],
    },
  )();
}

// /deals price-drop feed per site.md §4.3.
// Backed by the get_recent_price_drops() SQL function (migration 0008)
// wrapping the LAG-window CTE. Invoked as `SELECT * FROM get_recent_price_drops()`
// rather than supabase.rpc post-cut-4.
export interface PriceDropListing extends Listing {
  priorPrice: number;
  observedAt: string;
}

interface RpcPriceDropRow {
  id: number;
  vendor_id: number;
  raw_title: string;
  current_price: number | string | null;
  in_stock: boolean;
  image_url: string | null;
  product_url: string;
  first_seen_at: string;
  named_coral_id: number | null;
  match_confidence: 'exact' | 'alias' | 'fuzzy' | 'manual' | null;
  prior_price: number | string;
  observed_at: string;
  vendor_slug: string;
  vendor_display_name: string;
  named_coral_canonical_name: string | null;
  named_coral_slug: string | null;
  // named_coral_year_introduced omitted from RPC projection per Q-040-11
  // hold-position; PriceDropListing.namedCoralYearIntroduced always null
  // until Q-040-12 audit + schema migration restore.
  named_coral_origin_vendor: string | null;
}

function rpcRowToPriceDrop(row: RpcPriceDropRow): PriceDropListing {
  return {
    id: row.id,
    vendorSlug: row.vendor_slug,
    vendorDisplayName: row.vendor_display_name,
    rawTitle: row.raw_title,
    currentPrice: row.current_price !== null ? Number(row.current_price) : null,
    inStock: row.in_stock,
    imageUrl: row.image_url,
    productUrl: row.product_url,
    firstSeenAt: row.first_seen_at,
    matchConfidence: row.match_confidence,
    namedCoralCanonicalName: row.named_coral_canonical_name,
    namedCoralSlug: row.named_coral_slug,
    namedCoralOriginVendor: row.named_coral_origin_vendor,
    namedCoralYearIntroduced: null,
    priorPrice: Number(row.prior_price),
    observedAt: row.observed_at,
  };
}

export async function getRecentPriceDrops(): Promise<PriceDropListing[]> {
  const sql = getNeonSql();
  const rows = (await sql`SELECT * FROM get_recent_price_drops()`) as unknown as RpcPriceDropRow[];
  return rows.map(rpcRowToPriceDrop);
}

// /new arrivals feed per site.md §4.4.
// Backed by the get_recent_arrivals() SQL function (migration 0007) wrapping
// the UNION two-arm CTE. Invoked as `SELECT * FROM get_recent_arrivals()` post-cut-4.
export interface ArrivalListing extends Listing {
  event: 'just-listed' | 'back-in-stock';
  eventAt: string;
}

interface RpcArrivalRow {
  id: number;
  vendor_id: number;
  raw_title: string;
  current_price: number | string | null;
  in_stock: boolean;
  image_url: string | null;
  product_url: string;
  first_seen_at: string;
  named_coral_id: number | null;
  match_confidence: 'exact' | 'alias' | 'fuzzy' | 'manual' | null;
  event: 'just-listed' | 'back-in-stock';
  event_at: string;
  vendor_slug: string;
  vendor_display_name: string;
  named_coral_canonical_name: string | null;
  named_coral_slug: string | null;
  // named_coral_year_introduced omitted from RPC projection per Q-040-11
  // hold-position; ArrivalListing.namedCoralYearIntroduced always null until
  // Q-040-12 audit + schema migration restore.
  named_coral_origin_vendor: string | null;
}

function rpcRowToArrival(row: RpcArrivalRow): ArrivalListing {
  return {
    id: row.id,
    vendorSlug: row.vendor_slug,
    vendorDisplayName: row.vendor_display_name,
    rawTitle: row.raw_title,
    currentPrice: row.current_price !== null ? Number(row.current_price) : null,
    inStock: row.in_stock,
    imageUrl: row.image_url,
    productUrl: row.product_url,
    firstSeenAt: row.first_seen_at,
    matchConfidence: row.match_confidence,
    namedCoralCanonicalName: row.named_coral_canonical_name,
    namedCoralSlug: row.named_coral_slug,
    namedCoralOriginVendor: row.named_coral_origin_vendor,
    namedCoralYearIntroduced: null,
    event: row.event,
    eventAt: row.event_at,
  };
}

export async function getRecentArrivals(): Promise<ArrivalListing[]> {
  const sql = getNeonSql();
  const rows = (await sql`SELECT * FROM get_recent_arrivals()`) as unknown as RpcArrivalRow[];
  return rows.map(rpcRowToArrival);
}
