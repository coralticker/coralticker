// Originator full-name resolver per branding-guide.md §"Originator full names
// (per the `origin_vendor` field on named corals)". DB values are display-form;
// this resolver expands the canon abbreviations to display strings per the
// 8-value table + handles the sentinel + compound branches.
//
// Algorithm (branding-guide.md §"Compound-attribution shape"):
//   1. Sentinel exact-match — `community/canonical` → { suppress: true }.
//      Takes precedence over compound parsing because the literal contains a
//      slash that would otherwise route through the compound branch.
//   2. Compound branch — value containing `/` → split on `/`, look up each
//      component in the 8-value canon, join with ' / ' separator.
//   3. Single-value lookup — degenerate 1-component compound; same algorithm.
//
// Unknown components passthrough to the raw component value per the drift-add
// discipline in branding-guide.md §"Drift-add discipline for originator values".

export type OriginVendorRender =
  | { display: string; suppress?: false }
  | { suppress: true };

const SENTINEL_SUPPRESS = 'community/canonical';

// 8-value canon table per branding-guide.md §"Originator full names". Keys are
// the DB values (display-form already, NOT normalized identifiers); values are
// the expanded display strings rendered at lineage row + Lineage. field.
const ORIGIN_VENDOR_DISPLAY: Record<string, string> = {
  WWC: 'World Wide Corals',
  TSA: 'Top Shelf Aquatics',
  JF: 'Jason Fox Signature Corals',
  Battlecorals: 'Battlecorals',
  ORA: 'ORA',
  Tyree: 'Steve Tyree',
  Reeffarmers: 'Reeffarmers',
  // Both display as their own value: 'Pro Corals' is the plain full-name default
  // ("PC" is in-name shorthand only); 'GARF' is the self-branded-abbreviation
  // carve-out (ORA pattern, expansion reserved for /about-class contexts).
  'Pro Corals': 'Pro Corals',
  GARF: 'GARF',
};

function resolveComponent(raw: string): string {
  const trimmed = raw.trim();
  return ORIGIN_VENDOR_DISPLAY[trimmed] ?? trimmed;
}

export function resolveOriginVendor(raw: string): OriginVendorRender {
  const trimmed = raw.trim();
  // Sentinel match is normalized-on-input — case + whitespace drift
  // (`Community/Canonical`, `community / canonical`, etc.) still suppresses
  // cleanly. Defensive layer; no schema constraint imposed upstream.
  if (trimmed.toLowerCase().replace(/\s+/g, '') === SENTINEL_SUPPRESS) {
    return { suppress: true };
  }
  if (trimmed.includes('/')) {
    const components = trimmed.split('/').map(resolveComponent);
    return { display: components.join(' / ') };
  }
  return { display: resolveComponent(trimmed) };
}
