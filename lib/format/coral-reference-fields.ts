// Pure field-builder for the /guides <CoralReference> market line (CTK-162 D-4
// Variant B). Returns the DataRowField[] consumed by <DataRow> byte-for-byte
// (INV-01) — `Cheapest now./Listed now. — Vendor. — First seen.`. A distinct
// field set from buildPriceSummaryFields (no Lineage., a state-flexing first
// label, a lifetime First seen.), so it stays its own builder — but the two
// builders share the price + tie-render primitives (lib/format/price,
// lib/format/vendor-label) so those rules can't drift between the market surfaces.
//
// Label state-flex: "Cheapest now." when more than one in-stock listing offers
// the coral (there IS a cheapest-of-several); "Listed now." for a single listing
// (nothing to be cheapest of). The promoted price element renders the same value
// separately at display size — the value here stays canon 14px in the DataRow.
//
// First seen. = absolute "MMM YYYY" plain string (NOT the relative-time value-kind),
// ruled at /brand-manager (D-4 L81): it's a provenance anchor, not a freshness
// value, so it's exempt from §"Time format"'s relative rule; year-less "MMM D"
// is ambiguous-by-year and "N years ago" is more build for a vaguer result, so
// "MMM YYYY" — matching the eyebrow's UPDATED MON YYYY (one mental model).
//
// Returns [] when nothing is buyable now (OOS / unpriced) — the component then
// renders the honest-gap state instead of a row with a fabricated price.

import type { DataRowField } from '@/components/ui/data-row';
import type { Listing } from '@/lib/queries/listings';
import { renderTieVendors } from './vendor-label.ts';
import { formatPrice } from './price.ts';

const MONTHS = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
];

// "2024-03-04T…Z" → "Mar 2024". UTC so the calendar month/year matches the
// stored instant without tz drift (the provenance anchor is month-grain anyway).
function monthYear(iso: string): string {
  const d = new Date(iso);
  return `${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
}

export function buildCoralReferenceFields(
  listings: Listing[],
  firstSeenAt: string | null,
): DataRowField[] {
  // > 0, not just non-null: a phantom $0 must not surface as "Listed now. $0.00".
  const priced = listings.filter(
    (l) => l.inStock && l.currentPrice !== null && l.currentPrice > 0,
  );
  if (priced.length === 0) return [];

  const cheapestPrice = Math.min(...priced.map((l) => l.currentPrice as number));
  const tieRows = priced.filter((l) => l.currentPrice === cheapestPrice);

  // "cheapest-of-several" vs "single listing" — counted over in-stock priced
  // listings, not vendors (two listings at one vendor is still a cheapest-of).
  const label = priced.length > 1 ? 'Cheapest now' : 'Listed now';

  const fields: DataRowField[] = [
    { label, value: formatPrice(cheapestPrice) },
    { label: 'Vendor', value: renderTieVendors(tieRows) },
  ];

  // First seen. = lifetime, absolute "MMM YYYY" (provenance anchor). Omitted
  // (em-dash collapses) when the coral has no listing history to anchor to.
  if (firstSeenAt) {
    fields.push({ label: 'First seen', value: monthYear(firstSeenAt) });
  }

  return fields;
}
