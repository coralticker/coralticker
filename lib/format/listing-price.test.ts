// listing-price.ts has only type-only imports (erased by strip-types), so this
// pulls no '@/' aliases at runtime.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { buildPriceValue } from './listing-price.ts';
import type { Listing } from '../queries/listings.ts';

// Minimal in-stock, no-drop, no-markdown base. Each test overrides only the
// price-relevant fields.
function listing(overrides: Partial<Listing>): Listing {
  return {
    id: 1,
    vendorSlug: 'tidal-gardens',
    vendorDisplayName: 'Tidal Gardens',
    rawTitle: 'WWC Cabbage Patch',
    currentPrice: 100,
    compareAtPrice: null,
    inStock: true,
    imageUrl: null,
    productUrl: 'https://example.test/p',
    firstSeenAt: '2026-06-01T00:00:00.000Z',
    matchConfidence: null,
    namedCoralCanonicalName: null,
    namedCoralSlug: null,
    namedCoralOriginVendor: null,
    priorPrice: null,
    priceDropObservedAt: null,
    eventAt: null,
    ...overrides,
  };
}

test('OOS → invalidated (precedence over markdown)', () => {
  // Both OOS and marked down — OOS shape wins.
  assert.deepEqual(
    buildPriceValue(listing({ inStock: false, currentPrice: 245, compareAtPrice: 360 })),
    { kind: 'invalidated', value: '$245.00' },
  );
});

test('OOS auction (currentPrice null) → invalidated "price on request"', () => {
  assert.deepEqual(
    buildPriceValue(listing({ inStock: false, currentPrice: null })),
    { kind: 'invalidated', value: 'price on request' },
  );
});

test('CT-observed price-drop → price-drop-new (precedence over vendor-markdown)', () => {
  assert.deepEqual(
    buildPriceValue(listing({ currentPrice: 245, priorPrice: 300, compareAtPrice: 360 })),
    { kind: 'price-drop-new', oldValue: '$300.00', newValue: '$245.00' },
  );
});

test('vendor-markdown ≥5% → vendor-markdown', () => {
  assert.deepEqual(
    buildPriceValue(listing({ currentPrice: 245, compareAtPrice: 360 })),
    { kind: 'vendor-markdown', oldValue: '$360.00', newValue: '$245.00' },
  );
});

test('vendor-markdown: clean integer-dollar 5% mark fires (float-imprecision guard)', () => {
  // 3 * 1.05 = 3.1500000000000004 — the naive `compareAt >= current * 1.05`
  // form misses this; the subtract-then-epsilon form catches it.
  assert.deepEqual(
    buildPriceValue(listing({ currentPrice: 60, compareAtPrice: 63 })),
    { kind: 'vendor-markdown', oldValue: '$63.00', newValue: '$60.00' },
  );
});

test('vendor-markdown: below 5% → bare', () => {
  // 4% markdown — under threshold.
  assert.equal(
    buildPriceValue(listing({ currentPrice: 96, compareAtPrice: 100 })),
    '$96.00',
  );
});

test('F1 guard: currentPrice 0 with positive compareAt → bare $0.00, not phantom markdown', () => {
  assert.equal(
    buildPriceValue(listing({ currentPrice: 0, compareAtPrice: 50 })),
    '$0.00',
  );
});

test('bare current price when no markdown / drop / OOS', () => {
  assert.equal(buildPriceValue(listing({ currentPrice: 100 })), '$100.00');
});

test('bare auction (currentPrice null) → "price on request"', () => {
  assert.equal(buildPriceValue(listing({ currentPrice: null })), 'price on request');
});
