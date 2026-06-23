// /search three-class query helpers:
//   searchCorals()   — named_corals.normalized_name + auto-link
//                      aliases.alias_text, active-filtered, deduped to
//                      canonical; routes to /coral/[slug]
//   searchVendors()  — vendors.display_name, active + sentinel-guarded;
//                      routes to /vendor/[slug]
//   searchListings() — vendor_listings.normalized_title, in_stock = true,
//                      active vendor, first_seen_at DESC, LIMIT 51 overflow
//
// Per-token `ILIKE '%tok%'` AND-composed across the first SEARCH_TOKEN_CAP
// whitespace-split tokens of the parseSearchQuery output. Metacharacters escape
// with '!' + an explicit ESCAPE '!' clause — `ILIKE ALL(array)` cannot carry an
// ESCAPE clause, so predicates compose per-token instead. The Neon tagged
// template can't splice a variable predicate count, so each statement carries
// SEARCH_TOKEN_CAP fixed predicate slots with NULL constant-folding —
// `(${p}::text IS NULL OR x ILIKE ${p} ESCAPE '!')` — the same planner-fold
// idiom as getVendorInventory's category/includeOOS params.
//
// pg_trgm GIN on vendor_listings.normalized_title keeps the listings predicates
// indexed; vendors + the dictionary seq-scan by design.
//
// No unstable_cache: user-supplied q is unbounded key cardinality — caching
// per-q pollutes the Data Cache for one-shot reads. Direct per-request SQL.

import { getNeonSql } from '@/lib/db/neon';
import { buildIlikePatterns } from '@/lib/queries/listing-params';
import {
  mergeDropContext,
  rowToListing,
  type Listing,
  type VendorListingRow,
} from '@/lib/queries/listings';

// Listings cap + overflow flag: fetch LIMIT SEARCH_LISTINGS_LIMIT + 1, render
// SEARCH_LISTINGS_LIMIT, overflow drives the `50+ LISTINGS` eyebrow chunk (the
// `+` marks a floor per disclosure-symmetry).
export const SEARCH_LISTINGS_LIMIT = 50;

// Pattern builder (tokenize + escape + SEARCH_TOKEN_CAP) lives in
// listing-params.ts with the parser family — pure function, unit-tested there
// without this module's DB import chain.

// Fixed-slot padding for the SEARCH_TOKEN_CAP constant-folded predicates.
type PatternSlots = [
  string | null,
  string | null,
  string | null,
  string | null,
  string | null,
  string | null,
];

function toSlots(patterns: string[]): PatternSlots {
  return [
    patterns[0] ?? null,
    patterns[1] ?? null,
    patterns[2] ?? null,
    patterns[3] ?? null,
    patterns[4] ?? null,
    patterns[5] ?? null,
  ];
}

export interface CoralSearchHit {
  id: number;
  slug: string;
  canonicalName: string;
  coralType: string | null;
  originVendor: string | null;
  // Alias-side hits only: null on canonical-side hits — a row matching both
  // renders plain (canonical wins).
  matchedAlias: string | null;
}

interface CoralSearchRow {
  id: number;
  slug: string;
  canonical_name: string;
  coral_type: string | null;
  origin_vendor: string | null;
  matched_alias: string | null;
}

// Named corals: canonical-side ILIKE on normalized_name OR alias-side ILIKE on
// auto-link alias_text, both behind named_corals.active = true. flag-review rows
// carry named_coral_id IS NULL by CHECK constraint, so the correlation excludes
// them structurally; the match_behavior predicate stays explicit anyway. One row
// per coral by construction (no join fan-out; MIN() picks a deterministic alias
// when several match). NO in-stock EXISTS per the parity-divergence ruling
// (guide §"Default-render parity") — search answers "does CT know this coral";
// /coral/[slug]'s three-state canon is the honest answer behind the click.
// Order: canonical_name ASC per the /corals index precedent.
export async function searchCorals(
  normalizedQuery: string,
): Promise<CoralSearchHit[]> {
  const patterns = buildIlikePatterns(normalizedQuery);
  // Invariant guard — KEPT, not dead. The page null-checks parseSearchQuery
  // before any caller reaches here, so today this is unreachable. But the helper
  // is exported, and on an empty patterns array toSlots() pads all-NULL → every
  // `${p}::text IS NULL OR ...` slot folds to TRUE → an unfiltered full-table
  // result. This guard (and its siblings in searchVendors/searchListings) is the
  // second line of defense against that all-true predicate set.
  if (patterns.length === 0) return [];
  const [p1, p2, p3, p4, p5, p6] = toSlots(patterns);
  const sql = getNeonSql();

  const rows = (await sql`
    SELECT
      h.id,
      h.slug,
      h.canonical_name,
      h.coral_type,
      h.origin_vendor,
      CASE WHEN h.canonical_hit THEN NULL ELSE h.alias_match END AS matched_alias
    FROM (
      SELECT
        nc.id,
        nc.slug,
        nc.canonical_name,
        nc.coral_type,
        nc.origin_vendor,
        (
          (${p1}::text IS NULL OR nc.normalized_name ILIKE ${p1} ESCAPE '!')
          AND (${p2}::text IS NULL OR nc.normalized_name ILIKE ${p2} ESCAPE '!')
          AND (${p3}::text IS NULL OR nc.normalized_name ILIKE ${p3} ESCAPE '!')
          AND (${p4}::text IS NULL OR nc.normalized_name ILIKE ${p4} ESCAPE '!')
          AND (${p5}::text IS NULL OR nc.normalized_name ILIKE ${p5} ESCAPE '!')
          AND (${p6}::text IS NULL OR nc.normalized_name ILIKE ${p6} ESCAPE '!')
        ) AS canonical_hit,
        (
          SELECT MIN(a.alias_text)
          FROM aliases a
          WHERE a.named_coral_id = nc.id
            AND a.match_behavior = 'auto-link'
            AND (${p1}::text IS NULL OR a.alias_text ILIKE ${p1} ESCAPE '!')
            AND (${p2}::text IS NULL OR a.alias_text ILIKE ${p2} ESCAPE '!')
            AND (${p3}::text IS NULL OR a.alias_text ILIKE ${p3} ESCAPE '!')
            AND (${p4}::text IS NULL OR a.alias_text ILIKE ${p4} ESCAPE '!')
            AND (${p5}::text IS NULL OR a.alias_text ILIKE ${p5} ESCAPE '!')
            AND (${p6}::text IS NULL OR a.alias_text ILIKE ${p6} ESCAPE '!')
        ) AS alias_match
      FROM named_corals nc
      WHERE nc.active = true
    ) h
    WHERE h.canonical_hit OR h.alias_match IS NOT NULL
    ORDER BY h.canonical_name ASC
  `) as unknown as CoralSearchRow[];

  return rows.map((row) => ({
    id: row.id,
    slug: row.slug,
    canonicalName: row.canonical_name,
    coralType: row.coral_type,
    originVendor: row.origin_vendor,
    matchedAlias: row.matched_alias,
  }));
}

export interface VendorSearchHit {
  slug: string;
  displayName: string;
}

// Vendors: ILIKE on display_name (there is no vendors.name), active = true + the
// sentinel-slug guard — same belt-and-suspenders as getAllActiveVendors, because
// these rows route to /vendor/[slug] and a sentinel hit would route to a 404.
// display_name is not a normalized column; ILIKE carries the case fold and the
// 11-row scale makes accent divergence a non-issue.
export async function searchVendors(
  normalizedQuery: string,
): Promise<VendorSearchHit[]> {
  const patterns = buildIlikePatterns(normalizedQuery);
  // Invariant guard — see searchCorals: empty patterns → all-true predicate set
  // → unfiltered result. Kept as defense, not dead code.
  if (patterns.length === 0) return [];
  const [p1, p2, p3, p4, p5, p6] = toSlots(patterns);
  const sql = getNeonSql();

  const rows = (await sql`
    SELECT v.slug, v.display_name
    FROM vendors v
    WHERE v.active = true
      AND v.slug NOT LIKE '!_%' ESCAPE '!'
      AND (${p1}::text IS NULL OR v.display_name ILIKE ${p1} ESCAPE '!')
      AND (${p2}::text IS NULL OR v.display_name ILIKE ${p2} ESCAPE '!')
      AND (${p3}::text IS NULL OR v.display_name ILIKE ${p3} ESCAPE '!')
      AND (${p4}::text IS NULL OR v.display_name ILIKE ${p4} ESCAPE '!')
      AND (${p5}::text IS NULL OR v.display_name ILIKE ${p5} ESCAPE '!')
      AND (${p6}::text IS NULL OR v.display_name ILIKE ${p6} ESCAPE '!')
    ORDER BY v.display_name ASC
  `) as unknown as { slug: string; display_name: string }[];

  return rows.map((row) => ({
    slug: row.slug,
    displayName: row.display_name,
  }));
}

export interface ListingSearchResult {
  listings: Listing[];
  // True when a 51st row existed — the eyebrow renders `50+ LISTINGS`.
  overflow: boolean;
}

// Listings: ILIKE on normalized_title (render raw_title via the Listing shape),
// in_stock = true + active vendor (the OOS story lives one click behind the
// dictionary class). Sentinel-slug vendor guard matches the vendors class —
// sentinel rows are test fixtures. first_seen_at DESC; LIMIT cap + 1 drives the
// overflow flag. category IS DISTINCT FROM 'equipment' (CTK-186 step 2) gives the
// discovery surface parity with the feed reads — searching "adapter"/"neptune"
// must not surface equipment the /new + /vendor feeds now exclude. NULL-safe so
// reclassified None corals stay searchable.
//
// CT-observed drop context merges MARKERS ONLY: priorPrice + priceDropObservedAt
// populate so the struck-price Price field and the Q3 lead promotion render with
// cross-surface parity (a row that medals on /new medals here); eventAt
// deliberately stays null so Listed. and the day-bucket dividers keep reading the
// first_seen_at timestamp this surface orders by.
export async function searchListings(
  normalizedQuery: string,
): Promise<ListingSearchResult> {
  const patterns = buildIlikePatterns(normalizedQuery);
  // Invariant guard — see searchCorals: empty patterns → all-true predicate set
  // → unfiltered result. Kept as defense, not dead code.
  if (patterns.length === 0) return { listings: [], overflow: false };
  const [p1, p2, p3, p4, p5, p6] = toSlots(patterns);
  const sql = getNeonSql();

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
      AND vl.is_auction = false
      AND vl.category IS DISTINCT FROM 'equipment'
      AND v.active = true
      AND v.slug NOT LIKE '!_%' ESCAPE '!'
      AND (${p1}::text IS NULL OR vl.normalized_title ILIKE ${p1} ESCAPE '!')
      AND (${p2}::text IS NULL OR vl.normalized_title ILIKE ${p2} ESCAPE '!')
      AND (${p3}::text IS NULL OR vl.normalized_title ILIKE ${p3} ESCAPE '!')
      AND (${p4}::text IS NULL OR vl.normalized_title ILIKE ${p4} ESCAPE '!')
      AND (${p5}::text IS NULL OR vl.normalized_title ILIKE ${p5} ESCAPE '!')
      AND (${p6}::text IS NULL OR vl.normalized_title ILIKE ${p6} ESCAPE '!')
    ORDER BY vl.first_seen_at DESC
    LIMIT ${SEARCH_LISTINGS_LIMIT + 1}
  `) as unknown as VendorListingRow[];

  const overflow = rows.length > SEARCH_LISTINGS_LIMIT;
  const listings = rows.slice(0, SEARCH_LISTINGS_LIMIT).map(rowToListing);

  // Markers only — withEventAt: false keeps eventAt null so Listed. + the
  // /search day-bucket dividers read this surface's first_seen_at ordering
  // timestamp (see header comment).
  return {
    listings: await mergeDropContext(listings, { withEventAt: false }),
    overflow,
  };
}
