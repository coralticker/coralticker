// Pure field-builder for the price-history summary row (CTK-162 D-3, INV-01).
// Returns the canonical DataRowField[] consumed by BOTH the web <DataRow>
// (price-summary-row.tsx) and the non-DOM formatDataRow() — so this is the
// INV-01 parity surface: same field order, same labels, same em-dash collapse.
// Extracted from the component so the parity is unit-testable (see the
// co-located .test.ts), not asserted by eyeball.
//
// Vendor. source = getCoralAvailability (Jon-confirmed): the list arrives
// in-stock, cheapest-first; current cheapest = the min current_price, tie set =
// every in-stock row at that price, deduped by vendor (no ranking), ~3
// shorthands then +N. Lineage. = canon originator full name (no year — no such
// column). Sentinel originators suppress the field (em-dash collapses).

import type { DataRowField } from '@/components/ui/data-row';
import type { Listing } from '@/lib/queries/listings';
import type { NamedCoral } from '@/lib/queries/named-corals';
import { resolveOriginVendor } from './origin-vendor.ts';
import { renderTieVendors } from './vendor-label.ts';
import { formatPrice } from './price.ts';

export function buildPriceSummaryFields(
  listings: Listing[],
  coral: Pick<NamedCoral, 'origin_vendor'>,
): DataRowField[] {
  const priced = listings.filter((l) => l.inStock && l.currentPrice !== null);
  const cheapestPrice = priced.length
    ? Math.min(...priced.map((l) => l.currentPrice as number))
    : null;
  const tieRows =
    cheapestPrice !== null ? priced.filter((l) => l.currentPrice === cheapestPrice) : [];
  const cheapest = tieRows[0] ?? null;

  const fields: DataRowField[] = [];

  if (cheapestPrice !== null && cheapest) {
    fields.push({ label: 'Price', value: formatPrice(cheapestPrice) });
    fields.push({ label: 'Vendor', value: renderTieVendors(tieRows) });
  }

  // Truthy guard (mirrors buildLineageFields) — rules out null AND empty-string
  // drift in one boundary, no cast.
  if (coral.origin_vendor) {
    const origin = resolveOriginVendor(coral.origin_vendor);
    if (!('suppress' in origin && origin.suppress)) {
      fields.push({ label: 'Lineage', value: origin.display });
    }
  }

  if (cheapest) {
    fields.push({
      label: 'Listed',
      value: { kind: 'relative-time', timestamp: cheapest.eventAt ?? cheapest.firstSeenAt },
    });
  }

  return fields;
}
