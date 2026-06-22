// Vendor short-label canon (branding-guide §"Vendor shorthand" + the
// /brand-manager 2026-06-21 chart end-label map). BRAND CANON, not chart
// geometry — extracted out of lib/chart so the geometry module stays pure
// pixels. Consumed by the price-history end-labels (via an injected labelFor),
// the summary-row Vendor. field, and the chart aria-label.
//
// On THIS surface the chart end-label is space-constrained, so UC / TG take the
// R2R-native abbreviation (distinct from prose, where they'd be full names);
// the strong-confidence vendors take their short form; Battlecorals / Reef
// Chasers / ReefnBid stay full (their short forms are overloaded in the
// community).
//
// Rendering rule (canon): NEVER substitute an invented abbreviation — the only
// fallback for an unmapped vendor is the full display_name. Every current vendor
// is mapped; an un-canon vendor (a future scraper add) renders its full
// display_name until /brand-manager extends this table.

import type { Listing } from '@/lib/queries/listings';

const VENDOR_SHORTHAND: Record<string, string> = {
  wwc: 'WWC',
  jf: 'JF',
  tsa: 'TSA',
  pacific_east: 'PEA',
  poto: 'POTO',
  vivid_aquariums: 'Vivid',
  aquasd: 'Aqua SD',
  unique_corals: 'UC',
  tidal_gardens: 'TG',
  cornbred: 'Cornbred',
  battlecorals: 'Battlecorals',
  reef_chasers: 'Reef Chasers',
  reefnbid: 'ReefnBid',
};

export function vendorShorthand(slug: string, displayName: string): string {
  return VENDOR_SHORTHAND[slug] ?? displayName;
}

// Cross-vendor tie render: up to 3 shorthands then `+N`, comma-separated, DISTINCT
// vendors (a vendor with two listings at the cheapest price appears once), stable
// input order — a plain near-black string, no chrome register. Shared by the
// price-history summary row + the /guides market line, which both render the tie
// set of vendors at the cheapest in-stock price. Lives here (not in either
// field-builder) so the dedup + overflow rule can't drift between the two surfaces.
export function renderTieVendors(tieRows: Listing[]): string {
  const seen = new Set<string>();
  const shorthands: string[] = [];
  for (const row of tieRows) {
    if (seen.has(row.vendorSlug)) continue;
    seen.add(row.vendorSlug);
    shorthands.push(vendorShorthand(row.vendorSlug, row.vendorDisplayName));
  }
  if (shorthands.length <= 3) return shorthands.join(', ');
  return `${shorthands.slice(0, 3).join(', ')} +${shorthands.length - 3}`;
}
