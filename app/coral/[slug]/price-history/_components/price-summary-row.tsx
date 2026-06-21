// Summary row for the price-history page (CTK-162 D-3 INV-01). Renders
// `Price. — Vendor. — Lineage. — Listed.` via <DataRow> — the canonical em-dash
// data-row primitive, NOT a hand-rolled row. The field array is built by the
// pure buildPriceSummaryFields() (lib/format), which is the INV-01 parity
// surface (web <DataRow> ↔ non-DOM formatDataRow, unit-tested there).

import { DataRow } from '@/components/ui/data-row';
import type { Listing } from '@/lib/queries/listings';
import type { NamedCoral } from '@/lib/queries/named-corals';
import { buildPriceSummaryFields } from '@/lib/format/price-summary-fields';

interface Props {
  listings: Listing[]; // getCoralAvailability(coral.id) — in-stock, cheapest-first
  coral: Pick<NamedCoral, 'origin_vendor'>;
}

export function PriceSummaryRow({ listings, coral }: Props) {
  const fields = buildPriceSummaryFields(listings, coral);
  if (fields.length === 0) return null;
  return (
    <div className="mt-6">
      <DataRow fields={fields} />
    </div>
  );
}
