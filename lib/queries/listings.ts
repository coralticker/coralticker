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

// Spec-driven recency + pagination constants. Named per CTK-062 F-5 fold to
// keep literal sites grep-able back to their site.md spec source.
const PAGE_SIZE = 50; // site.md §4.5 — vendor-inventory pagination chunk.
const CORAL_RECENCY_DAYS = 7; // site.md §4.1 — /coral/[slug] availability window.
const VENDOR_RECENCY_DAYS = 14; // site.md §4.5 — /vendor/[slug] inventory window.
const MS_PER_DAY = 86_400_000;

export interface Listing {
  id: number;
  vendorSlug: string;
  vendorDisplayName: string;
  rawTitle: string;
  currentPrice: number | null;
  compareAtPrice: number | null;
  inStock: boolean;
  imageUrl: string | null;
  productUrl: string;
  firstSeenAt: string;
  matchConfidence: 'exact' | 'alias' | 'fuzzy' | 'manual' | null;
  namedCoralCanonicalName: string | null;
  namedCoralSlug: string | null;
  // Lineage origin per site.md §3.5.1 Lineage field rendering — only populated
  // when namedCoralCanonicalName is non-null (LEFT JOIN named_corals).
  // year_introduced removed per CTK-092 / Q-040-11 hold-position path-a.
  namedCoralOriginVendor: string | null;
  // CTK-047 B-3 cross-surface medal — populated by getListingDropContext()
  // LEFT JOIN against get_listing_lead_event(..., ARRAY['price-dropped']) RPC
  // (migration 0028) at getRecentDrops / getCoralAvailability / getVendorInventory.
  // Null when no CT-observed price-drop lead event exists within the 24h window
  // for the listing, or on helpers that don't merge (getRecentPriceDrops; /new
  // /arrivals populate from the RPC's price-dropped arm directly).
  priorPrice: number | null;
  priceDropObservedAt: string | null;
}

// Flat row shape returned by the JOIN below. PostgREST's nested-relation
// shape (vendors: {...}, named_corals: {...}) is gone post-cut-4; columns
// flatten with vendor_/named_coral_ prefixes.
interface VendorListingRow {
  id: number;
  raw_title: string;
  current_price: number | string | null;
  compare_at_price: number | string | null;
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
    compareAtPrice: row.compare_at_price != null ? Number(row.compare_at_price) : null,
    inStock: row.in_stock,
    imageUrl: row.image_url,
    productUrl: row.product_url,
    firstSeenAt: row.first_seen_at,
    matchConfidence: row.match_confidence,
    namedCoralCanonicalName: row.named_coral_canonical_name,
    namedCoralSlug: row.named_coral_slug,
    namedCoralOriginVendor: row.named_coral_origin_vendor,
    // CTK-047 B-3 — defaulted null; the LEFT JOIN merge in getRecentDrops /
    // getCoralAvailability / getVendorInventory populates these post-
    // rowToListing for listings present in get_listing_lead_event()'s
    // price-dropped arm.
    priorPrice: null,
    priceDropObservedAt: null,
  };
}

// CTK-047 B-1 — per-listing price-drop context.
// Wraps the get_listing_lead_event() RPC (migration 0028) with the
// event_filter=['price-dropped'] arm-scoped predicate for the three non-feed
// consumers (homepage strip, /coral/[slug], /vendor/[slug]). RPC returns rows
// only for listings whose LEAD event within the window is a price-drop;
// helpers LEFT JOIN the returned Map back into their primary Listing rows
// post-fetch, so a listing without a price-dropped lead event simply doesn't
// appear in the map.
//
// Map keys coerced to Number() because @neondatabase/serverless returns bigint
// columns as strings; existing rowToListing-shape code treats id as number per
// the cast-site interface, so the merge must coerce on both sides to keep key
// equality consistent.
export async function getListingDropContext(
  listingIds: number[],
  windowHours: number = 24,
): Promise<Map<number, { priorPrice: number; observedAt: string }>> {
  if (listingIds.length === 0) return new Map();
  const sql = getNeonSql();
  const rows = (await sql`
    SELECT id, prior_price, event_at
    FROM get_listing_lead_event(${listingIds}::bigint[], ${windowHours}, ARRAY['price-dropped']::text[])
  `) as unknown as { id: number | string; prior_price: number | string; event_at: string }[];
  const out = new Map<number, { priorPrice: number; observedAt: string }>();
  for (const row of rows) {
    out.set(Number(row.id), {
      priorPrice: Number(row.prior_price),
      observedAt: row.event_at,
    });
  }
  return out;
}

// Homepage strip per site.md §4.2 + Q-E default policy.
// Plain JOIN with LEFT JOIN named_corals; JS-side dedup on named_coral_id
// preserved from the Supabase impl (rather than pushing DISTINCT ON into SQL,
// which complicates the LIMIT semantics).
// CTK-080: first_seen_at > now() - 7d bound added 2026-05-24 — strip's
// just-listed lead-verb hardcode (recent-drops-strip.tsx L43) was rendering
// stale restocks as "just listed at $vendor" (Session 5 F-4). 7d matches
// CORAL_RECENCY_DAYS canon at L25.
export async function getRecentDrops(limit = 10): Promise<Listing[]> {
  const sql = getNeonSql();
  const overFetch = limit * 3;
  const sevenDaysAgo = new Date(Date.now() - CORAL_RECENCY_DAYS * MS_PER_DAY).toISOString();
  const rows = (await sql`
    SELECT
      vl.id,
      vl.raw_title,
      vl.current_price,
      vl.compare_at_price,
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
      AND vl.first_seen_at > ${sevenDaysAgo}
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
  // CTK-047 B-5 — LEFT JOIN drop context onto the rendered set so the strip's
  // B-4 deriveEvent() can surface price-drop variants alongside just-listed.
  const context = await getListingDropContext(out.map((l) => l.id));
  return out.map((l) => {
    const ctx = context.get(Number(l.id));
    return ctx
      ? { ...l, priorPrice: ctx.priorPrice, priceDropObservedAt: ctx.observedAt }
      : l;
  });
}

// /coral/[slug] per site.md §4.1.
// Filtered by named_coral_id AND last_seen_at > now() - interval '7 days'.
export async function getCoralAvailability(namedCoralId: number): Promise<Listing[]> {
  const sql = getNeonSql();
  const sevenDaysAgo = new Date(Date.now() - CORAL_RECENCY_DAYS * MS_PER_DAY).toISOString();

  const rows = (await sql`
    SELECT
      vl.id,
      vl.raw_title,
      vl.current_price,
      vl.compare_at_price,
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

  const listings = rows.map(rowToListing);
  // CTK-047 B-5 — LEFT JOIN drop context for cross-surface medal on
  // <VendorAvailabilityRow>. In-stock rows with priorPrice non-null render
  // price-drop-new at position 2 in the precedence chain.
  const context = await getListingDropContext(listings.map((l) => l.id));
  return listings.map((l) => {
    const ctx = context.get(Number(l.id));
    return ctx
      ? { ...l, priorPrice: ctx.priorPrice, priceDropObservedAt: ctx.observedAt }
      : l;
  });
}

// /vendor/[slug] per site.md §4.5.
// Filtered by vendor_id AND last_seen_at > now() - interval '14 days'.
// CTK-046: paginated via LIMIT PAGE_SIZE OFFSET ((page - 1) * PAGE_SIZE); default page = 1
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
// CTK-098 (2026-05-31): in-stock semantic flipped — default RESTRICTS to
// in_stock=true; includeOOS=true drops the predicate (mixed render). URL
// param renamed ?in-stock=1 → ?include-oos=1 per /brand-manager INV-02 lock.
// Predicate flipped from (NOT inStockParam OR in_stock=true) to
// (includeOOSParam OR in_stock=true). Cache-key prefix bumped to *V2 to
// invalidate pre-flip Data Cache entries (Next.js 15 unstable_cache persists
// across deploys per feedback_unstable_cache_shape_change.md) — cache key
// tuple shape unchanged.

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
  includeOOS: boolean = false,
): Promise<Listing[]> {
  return unstable_cache(
    async () => {
      const sql = getNeonSql();
      const fourteenDaysAgo = new Date(Date.now() - VENDOR_RECENCY_DAYS * MS_PER_DAY).toISOString();
      const offset = (page - 1) * PAGE_SIZE;

      // Optional filters collapse via SQL-side NULL/false constant folding:
      // `(${category}::text IS NULL OR vl.category = ${category})` lets a null
      // category short-circuit through the planner. includeOOS predicate
      // reads: false → (false OR in_stock=true) requires in_stock; true →
      // (true OR …) drops constraint. ORDER BY can't be parameterized —
      // switch on the allowlisted sort string and emit one of three full SQL
      // queries. Sort is validated at the view layer (page.tsx allowlist).
      const categoryParam = category ?? null;
      const includeOOSParam = includeOOS;

      const rows = (await (() => {
        if (sort === 'price-asc') {
          return sql`
            SELECT
              vl.id, vl.raw_title, vl.current_price, vl.compare_at_price, vl.in_stock,
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
              AND (${includeOOSParam}::boolean OR vl.in_stock = true)
            ORDER BY vl.current_price ASC NULLS LAST, vl.first_seen_at DESC
            LIMIT ${PAGE_SIZE} OFFSET ${offset}
          `;
        }
        if (sort === 'price-desc') {
          return sql`
            SELECT
              vl.id, vl.raw_title, vl.current_price, vl.compare_at_price, vl.in_stock,
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
              AND (${includeOOSParam}::boolean OR vl.in_stock = true)
            ORDER BY vl.current_price DESC NULLS LAST, vl.first_seen_at DESC
            LIMIT ${PAGE_SIZE} OFFSET ${offset}
          `;
        }
        // sort === 'newest'
        return sql`
          SELECT
            vl.id, vl.raw_title, vl.current_price, vl.compare_at_price, vl.in_stock,
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
            AND (${includeOOSParam}::boolean OR vl.in_stock = true)
          ORDER BY vl.first_seen_at DESC
          LIMIT ${PAGE_SIZE} OFFSET ${offset}
        `;
      })()) as unknown as VendorListingRow[];

      const listings = rows.map(rowToListing);
      // CTK-047 B-5 — LEFT JOIN drop context for cross-surface medal on
      // <VendorInventoryRow>. Same merge pattern as getRecentDrops /
      // getCoralAvailability; per-function call to getListingDropContext()
      // stays inline (below abstraction threshold per directive 2026-06-02).
      const context = await getListingDropContext(listings.map((l) => l.id));
      return listings.map((l) => {
        const ctx = context.get(Number(l.id));
        return ctx
          ? { ...l, priorPrice: ctx.priorPrice, priceDropObservedAt: ctx.observedAt }
          : l;
      });
    },
    [
      // V3 prefix bump 2026-06-01 (CTK-100 Wave-3) — Listing shape widened
      // with compareAtPrice; Next.js 15 unstable_cache persists Data Cache
      // across deploys per feedback_unstable_cache_shape_change.md, so V2
      // entries would deserialize without the new field for up to 600s.
      // V4 prefix bump 2026-06-02 (CTK-047 B-3) — Listing shape widened again
      // with priorPrice + priceDropObservedAt; same persistence concern. The
      // V3 entries would deserialize the new fields as undefined for up to
      // the revalidate window, breaking medal render on cached pages.
      'getVendorInventoryV4',
      String(vendorId),
      String(page),
      sort,
      category ?? '_',
      includeOOS ? '1' : '0',
    ],
    {
      // CTK-047 B-2 cascade — /vendor/[slug] medal-bearing surface; cadence
      // equalized to 5min with /coral/[slug] + /deals + homepage strip per
      // /lead-architect re-disposition 2026-06-02. Page-level revalidate at
      // app/vendor/[slug]/page.tsx:31 also drops 600 → 300 so the wrapped
      // data-cache doesn't outlast the page cache.
      revalidate: 300,
      tags: [
        `vendor-${vendorId}-page-${page}-${sort}-${category ?? '_'}-${includeOOS ? '1' : '0'}`,
      ],
    },
  )();
}

// /vendor/[slug] total-pages math per site.md §4.5 + CTK-046 + CTK-053.
// COUNT against the same 14-day recency window as getVendorInventory().
// No JOINs — vendor_id + last_seen_at + optional category + includeOOS
// drive the count; vendors / named_corals do not constrain row count.
// unstable_cache wrap per ISR-fold. Cache key drops sort + page (totals are
// invariant to both). CTK-098 (2026-05-31): cache-key prefix bumped to *V2
// to invalidate pre-flip Data Cache entries on the semantic flip.
export async function getVendorInventoryTotal(
  vendorId: number,
  category: ListingCategory | null = null,
  includeOOS: boolean = false,
): Promise<number> {
  return unstable_cache(
    async () => {
      const sql = getNeonSql();
      const fourteenDaysAgo = new Date(Date.now() - VENDOR_RECENCY_DAYS * MS_PER_DAY).toISOString();
      const categoryParam = category ?? null;
      const includeOOSParam = includeOOS;
      const rows = (await sql`
        SELECT COUNT(*) AS total
        FROM vendor_listings vl
        WHERE vl.vendor_id = ${vendorId}
          AND vl.last_seen_at > ${fourteenDaysAgo}
          AND (${categoryParam}::text IS NULL OR vl.category = ${categoryParam})
          AND (${includeOOSParam}::boolean OR vl.in_stock = true)
      `) as unknown as { total: number | string }[];
      const first = rows[0];
      return first ? Number(first.total) : 0;
    },
    [
      'getVendorInventoryTotalV2',
      String(vendorId),
      category ?? '_',
      includeOOS ? '1' : '0',
    ],
    {
      revalidate: 600,
      tags: [`vendor-${vendorId}-total-${category ?? '_'}-${includeOOS ? '1' : '0'}`],
    },
  )();
}

// /deals price-drop feed per site.md §4.3.
// Backed by the get_recent_price_drops() SQL function (migration 0008)
// wrapping the LAG-window CTE. Invoked as `SELECT * FROM get_recent_price_drops()`
// rather than supabase.rpc post-cut-4.
// CTK-061 migration 0009 caps the LAG window to 24h — limits price-drop event
// surfacing to the most recent observation pair, not all historical drops.
export interface PriceDropListing extends Listing {
  priorPrice: number;
  observedAt: string;
}

interface RpcPriceDropRow {
  id: number;
  vendor_id: number;
  raw_title: string;
  current_price: number | string | null;
  compare_at_price: number | string | null;
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
  named_coral_origin_vendor: string | null;
}

function rpcRowToPriceDrop(row: RpcPriceDropRow): PriceDropListing {
  return {
    id: row.id,
    vendorSlug: row.vendor_slug,
    vendorDisplayName: row.vendor_display_name,
    rawTitle: row.raw_title,
    currentPrice: row.current_price != null ? Number(row.current_price) : null,
    // CTK-109: get_recent_price_drops() (migration 0028 DROP+CREATE) widened
    // to project compare_at_price. /deals stays event-monotype on the
    // dedicated price-drop RPC; vendor-markdown renders alongside the
    // price-drop medal. Loose != null guards the T0→T1 deploy-window where
    // the pre-0028 function shape is still serving (column undefined, not
    // null) — strict !== would NaN-poison the field.
    compareAtPrice: row.compare_at_price != null ? Number(row.compare_at_price) : null,
    inStock: row.in_stock,
    imageUrl: row.image_url,
    productUrl: row.product_url,
    firstSeenAt: row.first_seen_at,
    matchConfidence: row.match_confidence,
    namedCoralCanonicalName: row.named_coral_canonical_name,
    namedCoralSlug: row.named_coral_slug,
    namedCoralOriginVendor: row.named_coral_origin_vendor,
    priorPrice: Number(row.prior_price),
    // CTK-047 B-3 base-Listing field — same data as observedAt below; PriceDropListing
    // extension narrows to non-null observedAt for the /deals discriminated union.
    priceDropObservedAt: row.observed_at,
    observedAt: row.observed_at,
  };
}

// CTK-109: /deals stays on get_recent_price_drops() (event-monotype; preserves
// multi-event-per-listing semantic). Migration 0028 DROP+CREATEs the function
// to add compare_at_price to the projection + AND vl.auction_end_time IS NULL
// to the WHERE clause (INV-05 #4 first-enforce). Body otherwise verbatim from
// migration 0026's CTK-099 in_stock=true filter.
export async function getRecentPriceDrops(): Promise<PriceDropListing[]> {
  const sql = getNeonSql();
  const rows = (await sql`SELECT * FROM get_recent_price_drops()`) as unknown as RpcPriceDropRow[];
  return rows.map(rpcRowToPriceDrop);
}

// /new arrivals feed per site.md §4.4.
// Backed by the get_listing_lead_event() SQL function (migration 0028)
// wrapping the three-arm UNION + ROW_NUMBER precedence ranking (price-dropped >
// back-in-stock > just-listed; Q2 brand-manager lock 2026-06-02). Invoked as
// `SELECT * FROM get_listing_lead_event(NULL, 24, NULL)` — NULL event_filter
// surfaces all three lead-event types on one row per listing. Migration 0029
// drops the predecessor get_recent_arrivals() post-deploy verify.
export interface ArrivalListing extends Listing {
  event: 'just-listed' | 'back-in-stock' | 'price-dropped';
  eventAt: string;
}

interface RpcArrivalRow {
  id: number;
  vendor_id: number;
  raw_title: string;
  current_price: number | string | null;
  compare_at_price: number | string | null;
  in_stock: boolean;
  image_url: string | null;
  product_url: string;
  first_seen_at: string;
  named_coral_id: number | null;
  match_confidence: 'exact' | 'alias' | 'fuzzy' | 'manual' | null;
  event: 'just-listed' | 'back-in-stock' | 'price-dropped';
  event_at: string;
  // Populated only on the price-dropped arm of get_listing_lead_event();
  // null on back-in-stock + just-listed arms.
  prior_price: number | string | null;
  vendor_slug: string;
  vendor_display_name: string;
  named_coral_canonical_name: string | null;
  named_coral_slug: string | null;
  named_coral_origin_vendor: string | null;
}

function rpcRowToArrival(row: RpcArrivalRow): ArrivalListing {
  return {
    id: row.id,
    vendorSlug: row.vendor_slug,
    vendorDisplayName: row.vendor_display_name,
    rawTitle: row.raw_title,
    currentPrice: row.current_price != null ? Number(row.current_price) : null,
    // CTK-109: get_listing_lead_event() projects compare_at_price across all
    // three arms. /new renders vendor-markdown on every arrival row regardless
    // of which lead event won. Loose != null guards the T0→T1 deploy-window
    // where get_recent_arrivals() may still be serving pre-swap (column
    // undefined, not null) — strict !== would NaN-poison the field.
    compareAtPrice: row.compare_at_price != null ? Number(row.compare_at_price) : null,
    inStock: row.in_stock,
    imageUrl: row.image_url,
    productUrl: row.product_url,
    firstSeenAt: row.first_seen_at,
    matchConfidence: row.match_confidence,
    namedCoralCanonicalName: row.named_coral_canonical_name,
    namedCoralSlug: row.named_coral_slug,
    namedCoralOriginVendor: row.named_coral_origin_vendor,
    // CTK-047 B-3 / Q2 amendment — /new now carries the price-dropped lead-
    // event arm. priorPrice + priceDropObservedAt populate only when this
    // row's lead event is a drop; null on back-in-stock + just-listed arms
    // (the RPC projects prior_price=NULL on those arms by construction).
    priorPrice: row.prior_price != null ? Number(row.prior_price) : null,
    priceDropObservedAt: row.event === 'price-dropped' ? row.event_at : null,
    event: row.event,
    eventAt: row.event_at,
  };
}

export async function getRecentArrivals(): Promise<ArrivalListing[]> {
  const sql = getNeonSql();
  const rows = (await sql`SELECT * FROM get_listing_lead_event(NULL, 24, NULL)`) as unknown as RpcArrivalRow[];
  return rows.map(rpcRowToArrival);
}
