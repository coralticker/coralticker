// coral-jsonld.ts has only a type-only import of Listing (erased by
// strip-types), so this pulls no '@/' aliases at runtime.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { buildCoralJsonLd, serializeJsonLd } from './coral-jsonld.ts';
import type { Listing } from '../queries/listings.ts';

// Minimal in-stock, priced base. Each test overrides only the relevant fields.
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
    productUrl: 'https://example.com/p/1',
    firstSeenAt: '2026-06-01T00:00:00Z',
    matchConfidence: 'exact',
    namedCoralCanonicalName: 'WWC Cabbage Patch',
    namedCoralSlug: 'wwc-cabbage-patch',
    namedCoralOriginVendor: null,
    priorPrice: null,
    priceDropObservedAt: null,
    eventAt: null,
    ...overrides,
  };
}

const SITE = 'https://coralticker.com';

function build(listings: Listing[], extra?: Partial<{ description: string | null }>) {
  return buildCoralJsonLd({
    siteUrl: SITE,
    canonicalName: 'WWC Cabbage Patch',
    description: extra?.description ?? null,
    slug: 'wwc-cabbage-patch',
    listings,
  });
}

function productOf(graph: object[]): Record<string, unknown> {
  const p = graph.find((n) => (n as Record<string, unknown>)['@type'] === 'Product');
  assert.ok(p, 'expected a Product node');
  return p as Record<string, unknown>;
}

function offersOf(graph: object[]): Record<string, unknown> | undefined {
  return productOf(graph).offers as Record<string, unknown> | undefined;
}

test('lowPrice/highPrice/offerCount span the in-stock priced rows', () => {
  const graph = build([
    listing({ id: 1, currentPrice: 120 }),
    listing({ id: 2, currentPrice: 80 }),
    listing({ id: 3, currentPrice: 200 }),
  ]);
  const offers = offersOf(graph);
  assert.ok(offers);
  assert.equal(offers.lowPrice, 80);
  assert.equal(offers.highPrice, 200);
  assert.equal(offers.offerCount, 3);
  assert.equal(offers.priceCurrency, 'USD');
  assert.equal(offers.availability, 'https://schema.org/InStock');
});

test('INV-05: null-price in-stock rows are excluded from the aggregate', () => {
  const graph = build([
    listing({ id: 1, currentPrice: 150 }),
    listing({ id: 2, currentPrice: null }), // price-on-request — must not set lowPrice
  ]);
  const offers = offersOf(graph);
  assert.ok(offers);
  assert.equal(offers.lowPrice, 150);
  assert.equal(offers.offerCount, 1);
});

test('INV-05: zero-price in-stock rows are excluded (currentPrice > 0 guard)', () => {
  const graph = build([
    listing({ id: 1, currentPrice: 0 }),
    listing({ id: 2, currentPrice: 90 }),
  ]);
  const offers = offersOf(graph);
  assert.ok(offers);
  assert.equal(offers.lowPrice, 90);
  assert.equal(offers.offerCount, 1);
});

test('out-of-stock priced rows are excluded', () => {
  const graph = build([
    listing({ id: 1, currentPrice: 75, inStock: false }),
    listing({ id: 2, currentPrice: 110, inStock: true }),
  ]);
  const offers = offersOf(graph);
  assert.ok(offers);
  assert.equal(offers.lowPrice, 110);
  assert.equal(offers.offerCount, 1);
});

test('no qualifying rows → Product carries NO offers (no deceptive lowPrice)', () => {
  const graph = build([
    listing({ id: 1, currentPrice: null, inStock: true }),
    listing({ id: 2, currentPrice: 90, inStock: false }),
    listing({ id: 3, currentPrice: 0, inStock: true }),
  ]);
  const product = productOf(graph);
  assert.equal(product.offers, undefined);
  // Product itself still renders (name/url) — the page exists regardless of stock.
  assert.equal(product.name, 'WWC Cabbage Patch');
});

test('description included only when present', () => {
  assert.equal(productOf(build([listing({})])).description, undefined);
  assert.equal(
    productOf(build([listing({})], { description: 'A chunky green chalice.' })).description,
    'A chunky green chalice.',
  );
});

test('serializeJsonLd escapes < so an embedded </script> cannot break out', () => {
  const graph = buildCoralJsonLd({
    siteUrl: SITE,
    canonicalName: 'Evil </script><script>alert(1)</script> Coral',
    description: null,
    slug: 'evil',
    listings: [listing({})],
  });
  const out = serializeJsonLd(graph);
  assert.ok(!out.includes('</script>'), 'no literal </script> survives serialization');
  assert.ok(out.includes('\\u003c'), 'angle brackets are unicode-escaped');
});

test('BreadcrumbList is Home > Corals > {coral} with absolute items', () => {
  const graph = build([listing({})]);
  const crumb = graph.find(
    (n) => (n as Record<string, unknown>)['@type'] === 'BreadcrumbList',
  ) as Record<string, unknown> | undefined;
  assert.ok(crumb);
  const items = crumb.itemListElement as Array<Record<string, unknown>>;
  assert.equal(items.length, 3);
  assert.deepEqual(
    items.map((i) => [i.position, i.name, i.item]),
    [
      [1, 'Home', SITE],
      [2, 'Corals', `${SITE}/corals`],
      [3, 'WWC Cabbage Patch', `${SITE}/coral/wwc-cabbage-patch`],
    ],
  );
});
