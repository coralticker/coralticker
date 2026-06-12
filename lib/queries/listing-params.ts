// The label records are the single source — allowlists derive from their keys
// (insertion order = brand-locked display order), the promoted bar's option
// rows derive from their entries, and the eyebrow chrome helper reads the same
// values. One record to edit when a category joins the seed list.
//
// Invalid URL inputs silently default (sort → 'newest', category → null) — no
// error states for URL tampering, the bare default is always the fallback.

import type { ListingCategory, ListingSort } from './listings';

// Symbol register (↑ / ↓) carries direction-as-data; word-pair LOW-TO-HIGH
// register rejected (extra chars, less data-density, register-conflict with
// PaginationNav's no-arrows-on-affordance discipline).
export const SORT_LABELS: Record<ListingSort, string> = {
  newest: 'NEWEST',
  'price-asc': 'PRICE ↑',
  'price-desc': 'PRICE ↓',
};

// 8 schema-aligned values in display-order (LPS top — DB-cardinality lead —
// then SPS / ZOA / MUSHROOM / CHALICE / CLAM / ANEMONE / SOFTIE). Hidden from
// filter UI: fish / invert / equipment / other — vendor-tail noise. Values are
// chrome-register labels (always ALL-CAPS per branding-guide §"Type label
// casing" chrome-inheritance); prose-register rendering goes through
// lib/format/type-label.ts instead.
export const CATEGORY_LABELS: Record<ListingCategory, string> = {
  lps: 'LPS',
  sps: 'SPS',
  zoa: 'ZOA',
  mushroom: 'MUSHROOM',
  chalice: 'CHALICE',
  clam: 'CLAM',
  anemone: 'ANEMONE',
  softie: 'SOFTIE',
};

const SORT_ALLOWLIST = Object.keys(SORT_LABELS) as readonly ListingSort[];
const CATEGORY_ALLOWLIST = Object.keys(
  CATEGORY_LABELS,
) as readonly ListingCategory[];

// Eyebrow count-chunk qualifier (branding-guide §"Eyebrow shape + slot") —
// chrome register reads straight off the record.
export function chromeCategoryLabel(category: ListingCategory): string {
  return CATEGORY_LABELS[category];
}

// Next.js delivers string[] when a URL carries the same query key twice
// (forum-quote manglers, tracking rewriters) — the pages' searchParams
// interfaces type these as string | undefined, which is a lie at runtime, and
// an array silently failed every allowlist check (default-wins where the
// visible URL says otherwise). First value wins, same as parseSearchQuery.
function firstValue(raw: string | string[] | undefined): string | undefined {
  return Array.isArray(raw) ? raw[0] : raw;
}

export function parseSort(raw: string | string[] | undefined): ListingSort {
  const single = firstValue(raw);
  if (!single) return 'newest';
  return (SORT_ALLOWLIST as readonly string[]).includes(single)
    ? (single as ListingSort)
    : 'newest';
}

export function parseCategory(
  raw: string | string[] | undefined,
): ListingCategory | null {
  const single = firstValue(raw);
  if (!single) return null;
  return (CATEGORY_ALLOWLIST as readonly string[]).includes(single)
    ? (single as ListingCategory)
    : null;
}

export function parseIncludeOOS(raw: string | string[] | undefined): boolean {
  return firstValue(raw) === '1';
}

// /search query normalizer. Mirrors the scrape-side runtime normalization that
// produced vendor_listings.normalized_title and named_corals.normalized_name
// (scrapers/common/normalize.py), same op order: lowercase → NFKD → strip
// combining marks → whitespace-collapse. An accent-bearing query must normalize
// the same way or it silently misses unaccented stored values. The trailing-junk
// strip stage is scrape-side only and deliberately not replicated — user queries
// don't carry SKU tails.
//
// Next.js delivers string[] when the URL carries duplicate ?q= keys — first
// value wins, matching the sibling parsers, instead of .normalize() throwing on
// an array in both generateMetadata and the page body.
//
// Empty / missing / whitespace-only → null (the page renders the bare frame,
// not an error). The raw (un-normalized) q echoes in the /search H1; this
// normalized form drives matching only.
export const SEARCH_QUERY_MAX_LENGTH = 80;

// Code-point-safe truncation to the query cap. `.slice(0, N)` counts UTF-16
// code units, so an N-unit cut lands mid-surrogate on an astral character: a
// lone surrogate echoes into the /search H1 + <title>, and a mangled trailing
// token reaches the matcher. Spreading to code points then rejoining truncates
// on whole code points (the cap now counts code points, not units — strictly
// more permissive for astral input, never less). Single application point for
// SEARCH_QUERY_MAX_LENGTH, consumed by both the parser (normalized) and the
// echo (raw) below.
export function clampSearchLength(s: string): string {
  return [...s].slice(0, SEARCH_QUERY_MAX_LENGTH).join('');
}

export function parseSearchQuery(
  raw: string | string[] | undefined,
): string | null {
  const single = Array.isArray(raw) ? raw[0] : raw;
  if (!single) return null;
  const normalized = clampSearchLength(
    single
      .toLowerCase()
      .normalize('NFKD')
      .replace(/\p{M}/gu, '')
      .replace(/\s+/g, ' ')
      .trim(),
  );
  return normalized === '' ? null : normalized;
}

// /search H1 + <title> query echo — raw (un-normalized) q, but clamped:
// trimmed + code-point-truncated to the parser's cap so an arbitrarily long
// ?q= can't blow out the title bar or the H1 line. Array guard mirrors
// parseSearchQuery — first value wins, so the echo names the value that drove
// matching. Lives here with the parser family rather than view-side so the
// surrogate-pair case is unit-testable.
export function clampSearchEcho(raw: string | string[] | undefined): string {
  const single = Array.isArray(raw) ? raw[0] : raw;
  return clampSearchLength((single ?? '').trim());
}

// /search pattern builder. Lives here with the parser — pure tokenize + escape
// over parseSearchQuery output, unit-testable without the DB import chain
// lib/queries/search.ts carries. Token cap 6: match on the first six tokens,
// drop the remainder. '!' escapes itself plus the ILIKE metacharacters % and _
// in one pass (JS template cooking collapses backslash escapes, hence '!' as
// the escape char); search.ts pairs every pattern with an explicit ESCAPE '!'
// clause — `ILIKE ALL(array)` can't carry one, so predicates compose per-token
// there.
export const SEARCH_TOKEN_CAP = 6;

export function buildIlikePatterns(normalizedQuery: string): string[] {
  return normalizedQuery
    .split(' ')
    .filter((tok) => tok !== '')
    .slice(0, SEARCH_TOKEN_CAP)
    .map((tok) => `%${tok.replace(/[!%_]/g, (c) => `!${c}`)}%`);
}
