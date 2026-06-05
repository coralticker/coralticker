// URL-state parsers + value→label records for <SortFilterBar> consumer
// routes — /vendor/[slug], /new, /deals (CTK-127 promotion; parsers
// previously co-located in app/vendor/[slug]/page.tsx at CTK-053).
//
// CTK-127 fold #4/#9: the label records are the single source — allowlists
// derive from their keys (insertion order = brand-locked display order), the
// promoted bar's option rows derive from their entries, and the eyebrow
// chrome helper reads the same values. One record to edit when a category
// joins the seed list.
//
// Invalid URL inputs silently default (sort → 'newest', category → null) per
// the canonical-chain discipline — no error states for URL tampering, the
// bare default is always the fallback.

import type { ListingCategory, ListingSort } from './listings';

// Sort labels per brand-manager session §Q-2 lock (CTK-053) — symbol
// register (↑ / ↓) carries direction-as-data; word-pair LOW-TO-HIGH register
// rejected (extra chars, less data-density, register-conflict with
// PaginationNav's no-arrows-on-affordance discipline).
export const SORT_LABELS: Record<ListingSort, string> = {
  newest: 'NEWEST',
  'price-asc': 'PRICE ↑',
  'price-desc': 'PRICE ↓',
};

// Category list locked at CTK-053 Session 1 Q-CTK053-3: 8 schema-aligned
// values in display-order per brand-manager session §Q-1 spec (LPS top —
// DB-cardinality lead — then SPS / ZOA / MUSHROOM / CHALICE / CLAM /
// ANEMONE / SOFTIE). Hidden from filter UI: fish / invert / equipment /
// other — vendor-tail noise. Values are chrome-register labels (always
// ALL-CAPS per branding-guide §"Type label casing" chrome-inheritance);
// prose-register rendering goes through lib/format/type-label.ts instead.
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

// Eyebrow count-chunk qualifier (branding-guide §"Eyebrow shape + slot"
// filtered-eyebrows lock) — chrome register reads straight off the record.
export function chromeCategoryLabel(category: ListingCategory): string {
  return CATEGORY_LABELS[category];
}

export function parseSort(raw: string | undefined): ListingSort {
  if (!raw) return 'newest';
  return (SORT_ALLOWLIST as readonly string[]).includes(raw)
    ? (raw as ListingSort)
    : 'newest';
}

export function parseCategory(raw: string | undefined): ListingCategory | null {
  if (!raw) return null;
  return (CATEGORY_ALLOWLIST as readonly string[]).includes(raw)
    ? (raw as ListingCategory)
    : null;
}

export function parseIncludeOOS(raw: string | undefined): boolean {
  return raw === '1';
}

// /search query normalizer (CTK-058 D-058-4). Mirrors the §3.3 runtime
// normalization that produced vendor_listings.normalized_title and
// named_corals.normalized_name (scrapers/common/normalize.py): lowercase +
// NFKD-unaccent + whitespace-collapse — an accent-bearing query must
// normalize the same way or it silently misses unaccented stored values
// (/review-plan fold #3). The trailing-junk strip stage is scrape-side only
// and deliberately not replicated — user queries don't carry SKU tails.
//
// Length-cap 80 applies post-normalization; a cap-cut partial trailing token
// still substring-matches per the D-058-1 ILIKE semantics. Empty / missing /
// whitespace-only → null (the page renders the bare frame, not an error).
// The raw (un-normalized) q echoes in the /search H1; this normalized form
// drives matching only.
export const SEARCH_QUERY_MAX_LENGTH = 80;

export function parseSearchQuery(raw: string | undefined): string | null {
  if (!raw) return null;
  const normalized = raw
    .normalize('NFKD')
    .replace(/\p{M}/gu, '')
    .toLowerCase()
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, SEARCH_QUERY_MAX_LENGTH);
  return normalized === '' ? null : normalized;
}

// /search pattern builder (CTK-058 D-058-1). Lives here with the parser —
// pure tokenize + escape over parseSearchQuery output, unit-testable without
// the DB import chain lib/queries/search.ts carries. Token cap 6
// (/review-plan suggestion fold): match on the first six tokens, drop the
// remainder. '!' escapes itself plus the ILIKE metacharacters % and _ in one
// pass (JS template cooking collapses backslash escapes, hence '!' as the
// escape char per feedback_ts_template_sql_escape_char); search.ts pairs
// every pattern with an explicit ESCAPE '!' clause — `ILIKE ALL(array)`
// can't carry one, so predicates compose per-token there.
export const SEARCH_TOKEN_CAP = 6;

export function buildIlikePatterns(normalizedQuery: string): string[] {
  return normalizedQuery
    .split(' ')
    .filter((tok) => tok !== '')
    .slice(0, SEARCH_TOKEN_CAP)
    .map((tok) => `%${tok.replace(/[!%_]/g, (c) => `!${c}`)}%`);
}
