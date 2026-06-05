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
// Exported (CTK-057 code-review fold #2): getAllNamedCoralsWithListings +
// the /corals empty-state copy derive from this constant directly, so the
// index window and the user-facing "7 days" string move with it.
export const CORAL_RECENCY_DAYS = 7; // site.md §4.1 — /coral/[slug] availability window.
const VENDOR_RECENCY_DAYS = 14; // site.md §4.5 — /vendor/[slug] inventory window.
// /new lead-event window (site.md §4.4) — passed to get_listing_lead_event()
// below AND the source for app/new/page.tsx's user-facing window copy
// (downtime fallback, filtered-empty line, filtered-zero eyebrow chunk), per
// the CTK-124 Q-1 one-constant pattern (CTK-127 fold #3). Window drift stays
// grep-able: query arg and label move together.
export const ARRIVALS_WINDOW_HOURS = 24;
export const MS_PER_DAY = 86_400_000;

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
  // CTK-047 Session 5 — natural event timestamp for the Listed. relative-time
  // field. Populated by getRecentArrivals (RPC event_at) + getRecentPriceDrops
  // (RPC observed_at); null on getRecentDrops + getCoralAvailability +
  // getVendorInventory (those surfaces fall back to firstSeenAt — the medal
  // carries the price-drop recency separately via Price field). <ListingCard>
  // Listed. consumes `listing.eventAt ?? listing.firstSeenAt`.
  eventAt: string | null;
}

// Flat row shape returned by the JOIN below. PostgREST's nested-relation
// shape (vendors: {...}, named_corals: {...}) is gone post-cut-4; columns
// flatten with vendor_/named_coral_ prefixes.
// Exported (CTK-058): lib/queries/search.ts projects the same column set for
// the /search listings class and reuses rowToListing below — one cast path,
// no shape fork.
export interface VendorListingRow {
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

export function rowToListing(row: VendorListingRow): Listing {
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
    // CTK-047 Session 5 — plain-JOIN surfaces (strip / coral / vendor) carry
    // no natural event timestamp; Listed. falls back to firstSeenAt.
    eventAt: null,
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
): Promise<Map<number, { priorPrice: number; observedAt: string; eventAt: string }>> {
  if (listingIds.length === 0) return new Map();
  const sql = getNeonSql();
  const rows = (await sql`
    SELECT id, prior_price, event_at
    FROM get_listing_lead_event(${listingIds}::bigint[], ${windowHours}, ARRAY['price-dropped']::text[])
  `) as unknown as { id: number | string; prior_price: number | string; event_at: string }[];
  // CTK-047 close-window: eventAt mirrors observedAt by definition (the CT-
  // observed price-drop event IS the observation). Surfaced explicitly so the
  // merge call-sites populate Listing.eventAt without re-reading the RPC row.
  const out = new Map<number, { priorPrice: number; observedAt: string; eventAt: string }>();
  for (const row of rows) {
    out.set(Number(row.id), {
      priorPrice: Number(row.prior_price),
      observedAt: row.event_at,
      eventAt: row.event_at,
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
  // Close-window addendum: eventAt populated so the homepage strip's price-
  // dropped rows show "X hours ago" on Listed. (the drop time) rather than
  // falling back to firstSeenAt.
  const context = await getListingDropContext(out.map((l) => l.id));
  return out.map((l) => {
    const ctx = context.get(Number(l.id));
    return ctx
      ? {
          ...l,
          priorPrice: ctx.priorPrice,
          priceDropObservedAt: ctx.observedAt,
          eventAt: ctx.eventAt,
        }
      : l;
  });
}

// /coral/[slug] per site.md §4.1.
// Filtered by named_coral_id AND last_seen_at > now() - interval '7 days'.
// CTK-126 D-2 (2026-06-05): in-stock default — default RESTRICTS to
// in_stock = true; includeOOS=true drops the predicate and restores the
// inventory-recon mixed render (CTK-098 semantic, same constant-folding
// predicate shape as getVendorInventory). The ?include-oos searchParams read
// flips /coral/[slug] pure-dynamic at runtime, so the fetch gains the
// unstable_cache wrap per the CTK-046 /vendor/[slug] precedent — key carries
// (namedCoralId, includeOOS); V1 prefix is this function's first cached
// generation (no pre-wrap Data Cache entries exist; bump on any future shape
// change per feedback_unstable_cache_shape_change). revalidate 300 matches
// the page-level cadence (CTK-047 B-2 medal-bearing surface). sevenDaysAgo
// computed inside the cached fn per getVendorInventory precedent.
//
// CTK-127 (2026-06-05): buy-intent ordering ladder per branding-guide
// §"Recent-first ordering by default" buy-intent carve-out (Jon-ratified
// 2026-06-05) — the surface answers "where do I buy this cheapest," and
// recent-first buried markdown rows below the fold at live eyeball. Ladder:
// in-stock priced rows current_price ASC (tie-break first_seen_at DESC) →
// NULL-price in-stock rows (price-on-request / auction class) → OOS rows
// last (toggled-on view only), newest-first within — recency is the
// staleness signal on invalidated rows; price-ordering them would rank by
// stale data. One ORDER BY implements the whole contract: the CASE yields
// NULL for every OOS row, collapsing the OOS block to the first_seen_at DESC
// tie-break.
//
// CTK-125 adjacency note (do NOT fold here): this query carries no
// v.active / sentinel-slug vendor guards — the Tier 4 vendor-guard sibling
// (CTK-125) owns that predicate change; mechanism-class discipline keeps it
// out of the CTK-126 D-2 edit.
export async function getCoralAvailability(
  namedCoralId: number,
  includeOOS: boolean = false,
): Promise<Listing[]> {
  return unstable_cache(
    async () => {
      const sql = getNeonSql();
      const sevenDaysAgo = new Date(Date.now() - CORAL_RECENCY_DAYS * MS_PER_DAY).toISOString();
      const includeOOSParam = includeOOS;

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
          AND (${includeOOSParam}::boolean OR vl.in_stock = true)
        ORDER BY vl.in_stock DESC,
                 CASE WHEN vl.in_stock THEN vl.current_price END ASC NULLS LAST,
                 vl.first_seen_at DESC
      `) as unknown as VendorListingRow[];

      const listings = rows.map(rowToListing);
      // CTK-047 B-5 — LEFT JOIN drop context for cross-surface medal on
      // <VendorAvailabilityRow>. In-stock rows with priorPrice non-null render
      // price-drop-new at position 2 in the precedence chain. Close-window
      // addendum: eventAt populated so Listed. reads "X hours ago" not "X days
      // ago" on rows with a recent CT-observed drop.
      const context = await getListingDropContext(listings.map((l) => l.id));
      return listings.map((l) => {
        const ctx = context.get(Number(l.id));
        return ctx
          ? {
              ...l,
              priorPrice: ctx.priorPrice,
              priceDropObservedAt: ctx.observedAt,
              eventAt: ctx.eventAt,
            }
          : l;
      });
    },
    // V2 prefix bump 2026-06-05 (CTK-127) — default ordering flipped
    // recent-first → buy-intent ladder (below). Not a shape change, but the
    // Data Cache persists across deploys per
    // feedback_unstable_cache_shape_change.md — without the bump, stale-order
    // arrays serve up to 300s post-deploy.
    ['getCoralAvailabilityV2', String(namedCoralId), includeOOS ? '1' : '0'],
    {
      revalidate: 300,
      tags: [`coral-${namedCoralId}-availability-${includeOOS ? '1' : '0'}`],
    },
  )();
}

// CTK-126 fold (/code-review #1, Tier 1A): cheap second signal for the
// /coral/[slug] third render state (all-OOS). Distinct-vendor count over the
// stock-UNFILTERED in-window set — getCoralAvailability's predicate MINUS
// the in_stock default — so the page can distinguish "listed but all out of
// stock" from "not listed" on the default render without widening the
// default availability query (/lead-backend call: separate count over
// query-widening). N = distinct vendors per the locked eyebrow shape
// (`N VENDORS · ALL OUT OF STOCK`, branding-guide §"Eyebrow shape + slot").
// Deliberately no vendor guards, matching getCoralAvailability — CTK-125
// adjacency; both gain them together if CTK-125 fires. Fetched by the page
// only when no in-stock row rendered (the toggled-on view derives N from
// its own rows instead).
export async function getCoralInWindowVendorCount(
  namedCoralId: number,
): Promise<number> {
  return unstable_cache(
    async () => {
      const sql = getNeonSql();
      const sevenDaysAgo = new Date(Date.now() - CORAL_RECENCY_DAYS * MS_PER_DAY).toISOString();
      const rows = (await sql`
        SELECT count(DISTINCT vl.vendor_id)::int AS n
        FROM vendor_listings vl
        WHERE vl.named_coral_id = ${namedCoralId}
          AND vl.last_seen_at > ${sevenDaysAgo}
      `) as unknown as { n: number }[];
      return rows[0]?.n ?? 0;
    },
    ['getCoralInWindowVendorCountV1', String(namedCoralId)],
    { revalidate: 300, tags: [`coral-${namedCoralId}-in-window-vendor-count`] },
  )();
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
      // Close-window addendum: eventAt populated for cross-surface Listed.
      // parity with /deals (medal-bearing row's Listed. reads "X hours ago").
      const context = await getListingDropContext(listings.map((l) => l.id));
      return listings.map((l) => {
        const ctx = context.get(Number(l.id));
        return ctx
          ? {
              ...l,
              priorPrice: ctx.priorPrice,
              priceDropObservedAt: ctx.observedAt,
              eventAt: ctx.eventAt,
            }
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
      // V5 prefix bump 2026-06-03 (CTK-047 close-window) — getVendorInventory's
      // post-merge cached shape now carries eventAt populated for rows with a
      // recent CT-observed drop (alongside priorPrice + priceDropObservedAt).
      // V4 entries would deserialize eventAt as undefined → Listed. ?? chain
      // falls back to firstSeenAt incorrectly on price-dropped rows for up to
      // 300s, showing "X days ago" instead of "X hours ago."
      'getVendorInventoryV5',
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
      // Cache-key stays V2 — return shape is `number`, unaffected by Listing
      // widens.
      'getVendorInventoryTotalV2',
      String(vendorId),
      category ?? '_',
      includeOOS ? '1' : '0',
    ],
    {
      // CTK-047 close-window — completes B-2 cadence cascade. aa24d96 dropped
      // getVendorInventory revalidate 600 → 300 but missed the sibling total
      // helper; pagination chrome was lagging up to 10 min behind the row
      // feed.
      revalidate: 300,
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
    // CTK-047 Session 5 — Listed. consumes eventAt ?? firstSeenAt; for /deals
    // this is the drop time (matches pre-Session-5 behavior driven by props.observedAt).
    eventAt: row.observed_at,
    observedAt: row.observed_at,
  };
}

// CTK-109: /deals stays on get_recent_price_drops() (event-monotype; preserves
// multi-event-per-listing semantic). Migration 0028 DROP+CREATEs the function
// to add compare_at_price to the projection + AND vl.auction_end_time IS NULL
// to the WHERE clause (INV-05 #4 first-enforce). Body otherwise verbatim from
// migration 0026's CTK-099 in_stock=true filter.
//
// CTK-127: sort + category params via wrapper JOIN, not RPC migration —
// category lives on vendor_listings, not in the RPC projection, so filter +
// sort apply in a wrapper around the function (JOIN on PK). RPC body
// untouched (INV-05 predicates stay inside it); bare call (newest, no
// category) stays the literal pre-CTK-127 statement — the function's own
// ORDER BY observed_at DESC (migration 0026 L111) carries the default order.
// Filtered-newest reproduces that ORDER BY explicitly (join output ordering
// isn't guaranteed). ORDER BY branches per allowlisted sort string — the
// Neon sql template can't parameterize ORDER BY; sort is validated at the
// view layer (lib/queries/listing-params.ts allowlist), no string
// interpolation into the template. unstable_cache wrap per CTK-046/126
// precedent: the searchParams read flips /deals dynamic at runtime; key
// carries (sort, category), V1 prefix is this function's first cached
// generation. revalidate 300 matches the page cadence.
export async function getRecentPriceDrops(
  sort: ListingSort = 'newest',
  category: ListingCategory | null = null,
): Promise<PriceDropListing[]> {
  return unstable_cache(
    async () => {
      const sql = getNeonSql();
      const categoryParam = category ?? null;

      const rows = (await (() => {
        if (sort === 'price-asc') {
          return sql`
            SELECT e.*
            FROM get_recent_price_drops() e
            JOIN vendor_listings vl ON vl.id = e.id
            WHERE (${categoryParam}::text IS NULL OR vl.category = ${categoryParam})
            ORDER BY e.current_price ASC NULLS LAST, e.observed_at DESC
          `;
        }
        if (sort === 'price-desc') {
          return sql`
            SELECT e.*
            FROM get_recent_price_drops() e
            JOIN vendor_listings vl ON vl.id = e.id
            WHERE (${categoryParam}::text IS NULL OR vl.category = ${categoryParam})
            ORDER BY e.current_price DESC NULLS LAST, e.observed_at DESC
          `;
        }
        // sort === 'newest'
        if (categoryParam !== null) {
          return sql`
            SELECT e.*
            FROM get_recent_price_drops() e
            JOIN vendor_listings vl ON vl.id = e.id
            WHERE vl.category = ${categoryParam}
            ORDER BY e.observed_at DESC
          `;
        }
        // Bare default — identical statement to pre-CTK-127.
        return sql`SELECT * FROM get_recent_price_drops()`;
      })()) as unknown as RpcPriceDropRow[];

      return rows.map(rpcRowToPriceDrop);
    },
    ['getRecentPriceDropsV1', sort, category ?? '_'],
    {
      revalidate: 300,
      tags: [`recent-price-drops-${sort}-${category ?? '_'}`],
    },
  )();
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

// CTK-127: sort + category params — same wrapper-JOIN shape and rationale as
// getRecentPriceDrops above (category via vendor_listings JOIN, RPC body +
// INV-05 predicates untouched, ORDER BY branch-per-allowlisted-sort, bare
// call literal pre-CTK-127). Filtered-newest reproduces the function's own
// ORDER BY event_at DESC (migration 0028 L253). unstable_cache key carries
// (sort, category), V1 first cached generation, revalidate 300 per page
// cadence.
export async function getRecentArrivals(
  sort: ListingSort = 'newest',
  category: ListingCategory | null = null,
): Promise<ArrivalListing[]> {
  return unstable_cache(
    async () => {
      const sql = getNeonSql();
      const categoryParam = category ?? null;

      const rows = (await (() => {
        if (sort === 'price-asc') {
          return sql`
            SELECT e.*
            FROM get_listing_lead_event(NULL, ${ARRIVALS_WINDOW_HOURS}, NULL) e
            JOIN vendor_listings vl ON vl.id = e.id
            WHERE (${categoryParam}::text IS NULL OR vl.category = ${categoryParam})
            ORDER BY e.current_price ASC NULLS LAST, e.event_at DESC
          `;
        }
        if (sort === 'price-desc') {
          return sql`
            SELECT e.*
            FROM get_listing_lead_event(NULL, ${ARRIVALS_WINDOW_HOURS}, NULL) e
            JOIN vendor_listings vl ON vl.id = e.id
            WHERE (${categoryParam}::text IS NULL OR vl.category = ${categoryParam})
            ORDER BY e.current_price DESC NULLS LAST, e.event_at DESC
          `;
        }
        // sort === 'newest'
        if (categoryParam !== null) {
          return sql`
            SELECT e.*
            FROM get_listing_lead_event(NULL, ${ARRIVALS_WINDOW_HOURS}, NULL) e
            JOIN vendor_listings vl ON vl.id = e.id
            WHERE vl.category = ${categoryParam}
            ORDER BY e.event_at DESC
          `;
        }
        // Bare default — identical statement to pre-CTK-127.
        return sql`SELECT * FROM get_listing_lead_event(NULL, ${ARRIVALS_WINDOW_HOURS}, NULL)`;
      })()) as unknown as RpcArrivalRow[];

      return rows.map(rpcRowToArrival);
    },
    ['getRecentArrivalsV1', sort, category ?? '_'],
    {
      revalidate: 300,
      tags: [`recent-arrivals-${sort}-${category ?? '_'}`],
    },
  )();
}
