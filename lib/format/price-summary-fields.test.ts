import { test } from 'node:test';
import assert from 'node:assert/strict';
import { buildPriceSummaryFields } from './price-summary-fields.ts';
import { formatDataRow } from './data-row.ts';
import type { Listing } from '@/lib/queries/listings';

// INV-01 parity: the summary row consumes the canonical DataRowField[] and the
// non-DOM formatDataRow() renders it to the em-dash form. These tests assert the
// shape (labels, order, em-dash collapse, tie render) by round-tripping through
// formatDataRow — non-tautological: hand-rolling the row, reordering fields, or
// dropping a label breaks them.

function listing(o: Partial<Listing>): Listing {
  return {
    id: 1,
    vendorSlug: 'wwc',
    vendorDisplayName: 'World Wide Corals',
    rawTitle: 'WWC Coral',
    currentPrice: 680,
    compareAtPrice: null,
    inStock: true,
    imageUrl: null,
    productUrl: 'https://x',
    firstSeenAt: '2026-06-21T08:00:00Z',
    matchConfidence: 'exact',
    namedCoralCanonicalName: 'JF Homewrecker',
    namedCoralSlug: 'jf-homewrecker',
    namedCoralOriginVendor: 'JF',
    priorPrice: null,
    priceDropObservedAt: null,
    eventAt: null,
    ...o,
  };
}
const NOW = new Date('2026-06-21T12:00:00Z');

test('buildPriceSummaryFields: cheapest single vendor → Price./Vendor./Lineage./Listed.', () => {
  const fields = buildPriceSummaryFields([listing({})], { origin_vendor: 'JF' });
  const row = formatDataRow(fields, NOW);
  assert.equal(
    row,
    'Price. $680.00 — Vendor. WWC — Lineage. Jason Fox Signature Corals — Listed. 4 hours ago',
  );
});

test('buildPriceSummaryFields: tie at min price → distinct vendor shorthands, no ranking', () => {
  const fields = buildPriceSummaryFields(
    [
      listing({ id: 1, vendorSlug: 'wwc', vendorDisplayName: 'World Wide Corals', currentPrice: 680 }),
      listing({ id: 2, vendorSlug: 'tsa', vendorDisplayName: 'Top Shelf Aquatics', currentPrice: 680 }),
      listing({ id: 3, vendorSlug: 'tsa', vendorDisplayName: 'Top Shelf Aquatics', currentPrice: 680 }), // dup vendor
    ],
    { origin_vendor: 'JF' },
  );
  // Vendor. value is the distinct-vendor tie set.
  const vendorField = fields.find((f) => f.label === 'Vendor');
  assert.equal(vendorField?.value, 'WWC, TSA');
});

test('buildPriceSummaryFields: sentinel lineage suppresses the field (em-dash collapse)', () => {
  const fields = buildPriceSummaryFields([listing({})], { origin_vendor: 'community/canonical' });
  assert.equal(fields.find((f) => f.label === 'Lineage'), undefined);
  const row = formatDataRow(fields, NOW);
  assert.ok(!row.includes('Lineage.'));
  assert.match(row, /^Price\. \$680\.00 — Vendor\. WWC — Listed\./);
});

test('buildPriceSummaryFields: all-OOS now → Lineage. only (no fabricated Price/Vendor)', () => {
  const fields = buildPriceSummaryFields(
    [listing({ inStock: false })],
    { origin_vendor: 'JF' },
  );
  assert.deepEqual(fields.map((f) => f.label), ['Lineage']);
});

test('buildPriceSummaryFields: +N overflow past 3 tied vendors', () => {
  const slugs = ['wwc', 'tsa', 'jf', 'poto', 'vivid_aquariums'];
  const fields = buildPriceSummaryFields(
    slugs.map((s, i) => listing({ id: i + 1, vendorSlug: s, vendorDisplayName: s, currentPrice: 500 })),
    { origin_vendor: 'JF' },
  );
  assert.equal(fields.find((f) => f.label === 'Vendor')?.value, 'WWC, TSA, JF +2');
});
