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
