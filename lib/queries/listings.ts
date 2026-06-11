// lib/queries/listings.ts
//
// Server-side query helpers consumed by Phase 2 view Server Components.
// Listing shape mirrors site.md §3.5.1 — the read shape of architecture-v1.md
// §1.4 vendor_listings + joined named_corals + vendors.
//
// Five helpers per site.md §4 contracts:
//   getRecentDrops()        — homepage strip per §4.2 (plain JOIN + JS dedup)
//   getRecentPriceDrops()   — /deals union per §4.3 + CTK-124 (RPC function 0033)
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
// /new page cap (CTK-124 Session 3b, /new fold Jon-ratified) — graduates the
// Q127-1 park: get_listing_lead_event's row_limit DEFAULT 100 (migration
// 0030) truncated INSIDE the RPC, before the wrapper's category filter, so
// filtered /new sampled the global newest-100. The bind now passes row_limit
// NULL (uncapped — 0030 documents LIMIT NULL ≡ LIMIT ALL) and this cap
// truncates wrapper-side, after filter/sort. Same relocation pattern as
// DEALS_PAGE_CAP below.
export const ARRIVALS_PAGE_CAP = 100;
// /deals union window (CTK-124 D-1, Jon-ratified 7d) — bound into
// get_recent_price_drops(p_window_days) below AND the source for
// app/deals/page.tsx's user-facing window copy (eyebrow middle chunk,
// empty-state lines), same one-constant pattern as ARRIVALS_WINDOW_HOURS.
// The RPC carries NO DB-side DEFAULT (migration 0033 header — overload
// ambiguity + single-source discipline): this constant is the only copy.
// Typed `number`, not the literal — the page-side singular-guard derivation
// compares against 1, which TS rejects on a literal-7 type.
export const DEALS_WINDOW_DAYS: number = 7;
// /deals page cap (CTK-124 Session 3b) — relocated from the RPC's internal
// LIMIT 250 (0033) to the view-layer wrapper (migration 0035 removes the
// SQL LIMIT): the RPC-side cap truncated BEFORE the wrapper applied
// filter/sort, so price-asc served "cheapest of the newest-250" and
// category filters sampled the same global slice. Wrapper-side, the cap
// truncates AFTER filter/sort — the right set every time. Not a render
// input: the eyebrow count stays drops.length (the 250+ overflow-disclosure
// canon Q stays parked).
export const DEALS_PAGE_CAP = 250;
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
  // Explicit row_limit NULL (CTK-124 close-fold rider (a), mirroring the
  // /new fold): the 0030 DEFAULT 100 was a latent truncation — every
  // consumer passes <= PAGE_SIZE (50) ids today, so the served set is
  // unchanged and the wrapping consumers' cache keys deliberately do NOT
  // bump; the explicit arg just closes the silent-bind hazard before a
  // consumer grows past 100 ids.
  const rows = (await sql`
    SELECT id, prior_price, event_at
    FROM get_listing_lead_event(${listingIds}::bigint[], ${windowHours}, ARRAY['price-dropped']::text[], NULL)
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
  // CTK-124: the 24h default here is DELIBERATE divergence from /deals'
  // DEALS_WINDOW_DAYS union window — homepage strip stays a 24h drop-context
  // surface per Jon strip ruling 2026-06-03 (CTK-111 trigger-gated). Do not
  // couple to the /deals constant.
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
// makes query-bearing /coral/[slug] requests render dynamically (bare URLs
// stay SSG/ISR via generateStaticParams — route table ●, CTK-126 #8
// evidence), so the fetch gains the
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
//
// Predicate coupling with the /corals index (CTK-128 (a) — assessed, paired
// cross-cites over extraction): the core triple here (named_coral_id +
// last_seen_at window + the in_stock=true default) is what the
// getAllNamedCoralsWithListings lateral (lib/queries/named-corals.ts)
// carries, coupled by convention per the Default-render parity rule
// (branding-guide §"State markers"); the window is constant-coupled via
// CORAL_RECENCY_DAYS. Two asymmetries are DELIBERATE and must survive any
// future refactor: (1) vendor guards are index-side only — see the CTK-125
// note above; (2) the includeOOS OR is destination-side only — parity is
// measured against this function's DEFAULT render, never the toggled view.
// A shared SQL fragment was rejected: neon's tagged template doesn't
// compose fragments without raw-string assembly, and a helper spanning two
// table-alias shapes would hide exactly the two asymmetries that matter.
// Edit the predicate here → check the lateral, and vice versa.
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
// adjacency; both gain them together if CTK-125 fires. Fired by the page
// unconditionally in a Promise.all alongside getCoralAvailability (CTK-128
// (g) — it was a serial await on the all-OOS default render); the value is
// consumed only when no in-stock row rendered (the toggled-on view derives
// N from its own rows instead).
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
// fold 2026-05-18): the searchParams read makes query-bearing requests
// render dynamically — bare URLs still prerender via generateStaticParams
// (route table ●, the CTK-126 #8-rejection build evidence; "flipped
// pure-dynamic" was this comment's old overclaim, corrected CTK-128 (e)) —
// so the wrap keeps those dynamic renders' data fetch on Data-Cache cadence.
// Key is the V5 tuple below: (vendorId, page, sort, category, includeOOS).
// revalidate = 300 since CTK-047 B-2 (this header's stale 600 corrected in
// the same CTK-128 pass), tandem with the page const. fourteenDaysAgo
// computed inside the cached fn — drifts up to 5 min within TTL window
// (mathematically acceptable on a 14-day window).
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

// /deals union feed per site.md §4.3 + CTK-124.
// Backed by get_recent_price_drops(p_window_days) (migration 0033) — two-arm
// union: CT-observed drops (price_history LAG window) ∪ active vendor
// markdowns whose attested onset (vendor_listings.markdown_started_at) falls
// in-window. One row per listing (ROW_NUMBER, price-dropped precedence per
// 0028 canon); both arms in_stock = true AND auction_end_time IS NULL
// (INV-05, enforced inside the RPC body). Window binds from
// DEALS_WINDOW_DAYS above. Supersedes the zero-arg 24h drops-only function
// (migrations 0008/0009/0026/0028 lineage; migration 0034 drops that
// signature after the CTK-124 verify cycle).
export interface PriceDropListing extends Listing {
  // null on markdown-only union rows (no CT-observed prior price — the slash
  // renders from compareAtPrice); non-null on drop-arm rows.
  priorPrice: number | null;
  // Union event time — drop arm: price_history.observed_at; markdown arm:
  // markdown_started_at (observation-attested onset). Field name kept from
  // the zero-arg era so /deals consumers (latestTimestamp, bucketTransition,
  // row keys) read it unchanged.
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
  // NULL on the markdown arm (migration 0033 — no fabricated prior).
  prior_price: number | string | null;
  event_at: string;
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
    // Nullable in the 0033 union projection (drop-arm rows without a live
    // vendor markdown). On markdown-only rows this carries the slash —
    // <ListingCard> renders vendor-markdown + Q3 lead promotion from it.
    compareAtPrice: row.compare_at_price != null ? Number(row.compare_at_price) : null,
    inStock: row.in_stock,
    imageUrl: row.image_url,
    productUrl: row.product_url,
    firstSeenAt: row.first_seen_at,
    matchConfidence: row.match_confidence,
    namedCoralCanonicalName: row.named_coral_canonical_name,
    namedCoralSlug: row.named_coral_slug,
    namedCoralOriginVendor: row.named_coral_origin_vendor,
    // CTK-124: guard before Number() — markdown-only rows carry prior_price
    // NULL, and Number(null) is 0, which would silently render a fake
    // "$0.00 → $X" drop on every markdown row.
    priorPrice: row.prior_price != null ? Number(row.prior_price) : null,
    // CTK-047 B-3 base-Listing field — union event_at on every row (markdown
    // rows: the attested onset). <ListingCard>'s CT-drop branches guard
    // conjunctively on priorPrice ≠ null, so markdown-only rows still route
    // to the vendor-markdown render despite this being populated.
    priceDropObservedAt: row.event_at,
    // CTK-047 Session 5 — Listed. consumes eventAt ?? firstSeenAt; for /deals
    // this is the drop time (drop arm) or markdown onset (markdown arm).
    eventAt: row.event_at,
    observedAt: row.event_at,
  };
}

// CTK-124 / CTK-127 #6 fold — shared ORDER-BY-ladder wrapper for the two
// event-RPC feeds (getRecentPriceDrops + getRecentArrivals). Both RPCs
// project `event_at` + `current_price`, so one ladder serves both; CTK-127
// landed the four-branch wrapper per-query because the pre-0033 drops RPC
// still projected `observed_at` — the union swap unifies the column and the
// extraction rides it (plan §Cross-CTK).
//
// Wrapper JOIN, not RPC migration, per the CTK-127 rationale: category lives
// on vendor_listings, not in the RPC projections; INV-05 predicates stay
// inside the RPC bodies. Bare call (newest, no category) skips the wrapper —
// each function's own ORDER BY event_at DESC carries the default order;
// filtered branches reproduce it explicitly (join output ordering isn't
// guaranteed).
//
// sql.unsafe() embeds ONLY module-level constants: `fnCall` is one of the
// two literal RPC invocations below (window values are exported constants,
// never user input), and the ORDER BY tail comes from the allowlisted-sort
// ladder map. Category and cap stay real binds; sort is validated at the
// view layer (lib/queries/listing-params.ts allowlist) before it reaches
// here. Never pass user input through `fnCall`.
//
// CTK-124 Session 3b: every ladder tail ends in the unique e.id tiebreak —
// event_at is massively non-unique (the 0033 cold-start backfill stamped
// thousands of onsets with one apply-moment timestamp), so without the
// tiebreak, order within ties was planner-dependent and could reshuffle
// call-to-call. With it, each tail is a total order, which makes the `cap`
// truncation below deterministic across revalidations.
const EVENT_ORDER_LADDER: Record<ListingSort, string> = {
  'price-asc': 'e.current_price ASC NULLS LAST, e.event_at DESC, e.id',
  'price-desc': 'e.current_price DESC NULLS LAST, e.event_at DESC, e.id',
  newest: 'e.event_at DESC, e.id',
};

// `cap` (CTK-124 Session 3b): view-layer row ceiling, applied as SQL LIMIT
// AFTER the ladder ORDER BY so truncation happens on the filtered/sorted
// set (migration 0035 removed the drops RPC's internal LIMIT — see
// DEALS_PAGE_CAP). Omitted cap binds LIMIT NULL ≡ no limit (same SQL-side
// constant-folding pattern as the category predicate).
async function orderedEventRows(
  fnCall: string,
  sort: ListingSort,
  category: ListingCategory | null,
  cap?: number,
): Promise<Record<string, unknown>[]> {
  if (cap !== undefined && cap < 1) {
    // cap=0 would bind LIMIT 0 (empty feed served silently) — a caller bug,
    // not a request shape. Assert loud rather than treating falsy as
    // uncapped (close-fold /code-review rider (c) — assert-≥1 chosen).
    throw new Error(`orderedEventRows: cap must be >= 1 (got ${cap})`);
  }
  const sql = getNeonSql();
  const categoryParam = category ?? null;
  const capParam = cap ?? null;
  if (sort === 'newest' && categoryParam === null) {
    // Bare branch — no JOIN needed; one template capped or not (LIMIT NULL
    // ≡ no limit). The wrapper owns the total order on every path: the
    // arrivals RPC's internal ORDER BY (migration 0030) carries no id
    // tiebreak, so "function-internal order" was never contractual here
    // (close-fold rider (b) — the uncapped passthrough was dead code with
    // a false comment).
    return sql`
      SELECT e.*
      FROM ${sql.unsafe(fnCall)} e
      ORDER BY ${sql.unsafe(EVENT_ORDER_LADDER.newest)}
      LIMIT ${capParam}
    `;
  }
  return sql`
    SELECT e.*
    FROM ${sql.unsafe(fnCall)} e
    JOIN vendor_listings vl ON vl.id = e.id
    WHERE (${categoryParam}::text IS NULL OR vl.category = ${categoryParam})
    ORDER BY ${sql.unsafe(EVENT_ORDER_LADDER[sort])}
    LIMIT ${capParam}
  `;
}

// CTK-124: bind swapped to the one-arg union RPC (migration 0033) —
// get_recent_price_drops(DEALS_WINDOW_DAYS). Scope widens 24h CT-observed
// drops only → 7d drops ∪ active vendor markdowns, one row per listing
// (retires the zero-arg function's multi-event-per-listing semantic).
// Sort/category wrapper via orderedEventRows above (CTK-127 shape, ladder
// extracted per fold #6). unstable_cache wrap per CTK-046/126 precedent:
// the searchParams read flips /deals dynamic at runtime; key carries
// (sort, category); revalidate 300 matches the page cadence.
export async function getRecentPriceDrops(
  sort: ListingSort = 'newest',
  category: ListingCategory | null = null,
): Promise<PriceDropListing[]> {
  return unstable_cache(
    async () => {
      const rows = (await orderedEventRows(
        `get_recent_price_drops(${DEALS_WINDOW_DAYS})`,
        sort,
        category,
        DEALS_PAGE_CAP,
      )) as unknown as RpcPriceDropRow[];

      return rows.map(rpcRowToPriceDrop);
    },
    [
      // V2 prefix bump 2026-06-06 (CTK-124) — RPC swapped to the one-arg
      // union: row shape renames observed_at → event_at, prior_price goes
      // nullable, scope widens to the 7d union. The Data Cache persists
      // across deploys per feedback_unstable_cache_shape_change.md — V1
      // entries would keep serving the old shape/scope for up to 300s.
      // V3 prefix bump 2026-06-06 (CTK-124 Session 3b) — output set changes
      // twice over: migration 0035 lands the markdown-arm 5% floor in the
      // RPC, and the 250 cap relocates RPC→wrapper so truncation happens
      // after filter/sort (filtered/sorted views admit the full window
      // instead of sampling the global newest-250). Same persistence
      // concern as above.
      'getRecentPriceDropsV3',
      sort,
      category ?? '_',
    ],
    {
      revalidate: 300,
      tags: [`recent-price-drops-${sort}-${category ?? '_'}`],
    },
  )();
}

// /deals eyebrow LATEST source (CTK-124 close-fold, /code-review round-2
// #1, Tier 1B): post-0035 the wrapper cap truncates AFTER the ladder sort,
// so under price sorts max(rendered.observedAt) reads the capped slice, not
// the window — the eyebrow could claim "LATEST 2 DAYS AGO" while a drop
// landed an hour ago. Canon constrains the fix (branding-guide §"Eyebrow
// shape + slot" filtered-eyebrows lock: no eyebrow change under sort — the
// chunk can't drop on sorted views), so the true latest comes from a
// dedicated cap=1 newest-ladder call. Same category arg keeps the filtered
// eyebrow in-category-honest. Own cache key, same revalidate cadence.
export async function getLatestPriceDropAt(
  category: ListingCategory | null = null,
): Promise<string | null> {
  return unstable_cache(
    async () => {
      const rows = (await orderedEventRows(
        `get_recent_price_drops(${DEALS_WINDOW_DAYS})`,
        'newest',
        category,
        1,
      )) as unknown as RpcPriceDropRow[];
      return rows[0]?.event_at ?? null;
    },
    ['getLatestPriceDropAtV1', category ?? '_'],
    {
      revalidate: 300,
      tags: [`latest-price-drop-${category ?? '_'}`],
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

// CTK-127: sort + category params via the shared orderedEventRows wrapper
// (ladder extracted at CTK-124 per fold #6 — see the helper's header for the
// sql.unsafe constants-only invariant). CTK-124 Session 3b /new fold
// (Jon-ratified, graduates the Q127-1 park): row_limit binds explicit NULL
// and ARRIVALS_PAGE_CAP caps wrapper-side, so filtered/sorted /new admits
// the full 24h window instead of sampling the RPC's internal newest-100.
// unstable_cache key carries (sort, category), V2 generation, revalidate
// 300 per page cadence.
export async function getRecentArrivals(
  sort: ListingSort = 'newest',
  category: ListingCategory | null = null,
): Promise<ArrivalListing[]> {
  return unstable_cache(
    async () => {
      const rows = (await orderedEventRows(
        // Explicit fourth arg NULL = row_limit uncapped (migration 0030
        // semantics) — the silent DEFAULT 100 truncated pre-filter; the
        // wrapper cap below truncates post-filter/sort instead.
        `get_listing_lead_event(NULL, ${ARRIVALS_WINDOW_HOURS}, NULL, NULL)`,
        sort,
        category,
        ARRIVALS_PAGE_CAP,
      )) as unknown as RpcArrivalRow[];

      return rows.map(rpcRowToArrival);
    },
    [
      // V2 prefix bump 2026-06-06 (CTK-124 Session 3b /new fold) — row_limit
      // NULL + wrapper cap change the served set on filtered/sorted views
      // (full-window admission instead of the global newest-100 sample). The
      // Data Cache persists across deploys per
      // feedback_unstable_cache_shape_change.md.
      'getRecentArrivalsV2',
      sort,
      category ?? '_',
    ],
    {
      revalidate: 300,
      tags: [`recent-arrivals-${sort}-${category ?? '_'}`],
    },
  )();
}
