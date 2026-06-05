// URL-state parsers for <SortFilterBar> consumer routes — /vendor/[slug],
// /new, /deals (CTK-127 promotion; previously co-located in
// app/vendor/[slug]/page.tsx at CTK-053). Allowlists mirror the CTK-053 data
// contract: invalid inputs silently default (sort → 'newest', category →
// null) per the canonical-chain discipline — no error states for URL
// tampering, the bare default is always the fallback.

import type { ListingCategory, ListingSort } from './listings';

const SORT_ALLOWLIST: readonly ListingSort[] = [
  'newest',
  'price-asc',
  'price-desc',
];

export function parseSort(raw: string | undefined): ListingSort {
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

export function parseCategory(raw: string | undefined): ListingCategory | null {
  if (!raw) return null;
  return (CATEGORY_ALLOWLIST as readonly string[]).includes(raw)
    ? (raw as ListingCategory)
    : null;
}

export function parseIncludeOOS(raw: string | undefined): boolean {
  return raw === '1';
}
