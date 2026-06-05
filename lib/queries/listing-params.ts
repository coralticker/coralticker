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
