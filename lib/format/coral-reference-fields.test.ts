import { test } from 'node:test';
import assert from 'node:assert/strict';
import { buildCoralReferenceFields } from './coral-reference-fields.ts';
import { formatDataRow } from './data-row.ts';
import type { Listing } from '@/lib/queries/listings';

// The builder feeds <DataRow> byte-for-byte (INV-01). These tests round-trip
// through formatDataRow() — non-tautological: hand-rolling the row, reordering
// fields, mislabelling the state-flex, or dropping the $0 / OOS guard breaks
// them (each assertion fails if the guarded code is removed).

function listing(o: Partial<Listing>): Listing {
  return {
    id: 1,
    vendorSlug: 'wwc',
    vendorDisplayName: 'World Wide Corals',
    rawTitle: 'WWC Coral',
    currentPrice: 540,
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
// First seen. is a provenance anchor → absolute "MMM YYYY", NEVER relative
// (ruled at /brand-manager, D-4 L81). Asserts the absolute string for both an old
// and a recent first-seen — neither produces a relative phrase.
const FIRST_SEEN_OLD = '2024-03-04T12:00:00Z';
const FIRST_SEEN_RECENT = '2026-06-19T12:00:00Z'; // 2 days before NOW — still absolute

test('cheapest-of-several → "Cheapest now." + cheapest floor + First seen. (absolute MMM YYYY)', () => {
  const fields = buildCoralReferenceFields(
    [
      listing({ id: 1, vendorSlug: 'wwc', vendorDisplayName: 'World Wide Corals', currentPrice: 540 }),
      listing({ id: 2, vendorSlug: 'tsa', vendorDisplayName: 'Top Shelf Aquatics', currentPrice: 700 }),
    ],
    FIRST_SEEN_OLD,
  );
  assert.equal(
    formatDataRow(fields, NOW),
    'Cheapest now. $540.00 — Vendor. WWC — First seen. Mar 2024',
  );
});

test('recent first-seen → still absolute "Jun 2026", not a relative phrase', () => {
  const fields = buildCoralReferenceFields([listing({ currentPrice: 420 })], FIRST_SEEN_RECENT);
  assert.equal(
    formatDataRow(fields, NOW),
    'Listed now. $420.00 — Vendor. WWC — First seen. Jun 2026',
  );
});

test('single listing → "Listed now." state-flex (not "Cheapest now.")', () => {
  const fields = buildCoralReferenceFields([listing({ currentPrice: 420 })], FIRST_SEEN_OLD);
  const first = fields[0];
  assert.equal(first?.label, 'Listed now');
  assert.equal(first?.value, '$420.00');
});

test('tie at the cheapest price → distinct vendors, no ranking, dup vendor collapses', () => {
  const fields = buildCoralReferenceFields(
    [
      listing({ id: 1, vendorSlug: 'tsa', vendorDisplayName: 'Top Shelf Aquatics', currentPrice: 520 }),
      listing({ id: 2, vendorSlug: 'aqua-sd', vendorDisplayName: 'Aqua SD', currentPrice: 520 }),
      listing({ id: 3, vendorSlug: 'tsa', vendorDisplayName: 'Top Shelf Aquatics', currentPrice: 520 }), // dup
    ],
    FIRST_SEEN_OLD,
  );
  const vendor = fields.find((f) => f.label === 'Vendor');
  assert.equal(vendor?.value, 'TSA, Aqua SD');
});

test('more than 3 distinct tie vendors → "+N" overflow', () => {
  const fields = buildCoralReferenceFields(
    [
      listing({ id: 1, vendorSlug: 'wwc', vendorDisplayName: 'World Wide Corals', currentPrice: 500 }),
      listing({ id: 2, vendorSlug: 'tsa', vendorDisplayName: 'Top Shelf Aquatics', currentPrice: 500 }),
      listing({ id: 3, vendorSlug: 'aqua-sd', vendorDisplayName: 'Aqua SD', currentPrice: 500 }),
      listing({ id: 4, vendorSlug: 'pea', vendorDisplayName: 'Pacific East Aquaculture', currentPrice: 500 }),
    ],
    FIRST_SEEN_OLD,
  );
  const vendor = fields.find((f) => f.label === 'Vendor');
  assert.match(String(vendor?.value), /\+1$/);
});

test('nothing buyable (all OOS) → [] so the component renders the honest gap, not a $-row', () => {
  const fields = buildCoralReferenceFields(
    [listing({ inStock: false, currentPrice: 540 })],
    FIRST_SEEN_OLD,
  );
  assert.deepEqual(fields, []);
});

test('phantom $0 in-stock row is not buyable → [] (no "$0.00")', () => {
  const fields = buildCoralReferenceFields([listing({ currentPrice: 0 })], FIRST_SEEN_OLD);
  assert.deepEqual(fields, []);
});

test('null first-seen → First seen. field omitted (em-dash collapse)', () => {
  const fields = buildCoralReferenceFields([listing({ currentPrice: 420 })], null);
  assert.equal(
    formatDataRow(fields, NOW),
    'Listed now. $420.00 — Vendor. WWC',
  );
  assert.equal(fields.find((f) => f.label === 'First seen'), undefined);
});

// ── INV-01 guarantee: exercise the contract, don't echo it ───────────────────
// The canon em-dash data row is rendered by the SHARED DataRow layer — formatDataRow
// adds the "label." period (data-row.ts L17) and joins fields with " — " (L18); the
// web <DataRow> renders the same content to DOM (live-verified on the served guide).
// INV-01 holds for the guides market row ONLY IF buildCoralReferenceFields emits
// STRUCTURED, punctuation-free fields so that shared layer owns the period + the
// separator. These two tests fail if the builder hand-rolls EITHER — a baked period
// in a label, an em-dash smuggled into a value, or a pre-joined single-field row.
// (The exact-string asserts above can be satisfied by a lucky hand-roll; these
// can't — they pin the period and the em-dash to the layer that supplies them.)

test('INV-01: labels carry NO trailing period — the "." is the shared layer\'s, not the builder\'s', () => {
  const fields = buildCoralReferenceFields(
    [
      listing({ id: 1, vendorSlug: 'wwc', vendorDisplayName: 'World Wide Corals', currentPrice: 540 }),
      listing({ id: 2, vendorSlug: 'tsa', vendorDisplayName: 'Top Shelf Aquatics', currentPrice: 700 }),
    ],
    FIRST_SEEN_OLD,
  );
  // If the builder baked "Cheapest now." (period) into the label, formatDataRow
  // would emit "Cheapest now.." — so the period must be absent from the raw label.
  for (const f of fields) {
    assert.ok(
      !f.label.includes('.'),
      `label "${f.label}" must not bake the canon period — DataRow/formatDataRow adds it`,
    );
  }
});

test('INV-01: no string value carries the " — " separator, and the row partitions to exactly one segment per field', () => {
  const fields = buildCoralReferenceFields(
    [
      listing({ id: 1, vendorSlug: 'tsa', vendorDisplayName: 'Top Shelf Aquatics', currentPrice: 520 }),
      listing({ id: 2, vendorSlug: 'aqua-sd', vendorDisplayName: 'Aqua SD', currentPrice: 520 }), // tie → "TSA, Aqua SD"
    ],
    FIRST_SEEN_OLD,
  );
  // The em-dash is the join's, never a value's: a hand-rolled em-dash (e.g. a
  // pre-joined "$520 — Vendor. TSA" value) would put one inside a field.
  for (const f of fields) {
    if (typeof f.value === 'string') {
      assert.ok(
        !f.value.includes('—'),
        `value "${f.value}" must not contain an em-dash — the join owns the separator`,
      );
    }
  }
  // Separator count is structural: splitting the rendered row on " — " yields
  // exactly fields.length segments (count === fields.length - 1). A smuggled
  // em-dash would inflate this past fields.length.
  const segments = formatDataRow(fields, NOW).split(' — ');
  assert.equal(segments.length, fields.length);
});
