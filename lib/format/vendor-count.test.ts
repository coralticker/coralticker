import { test } from 'node:test';
import assert from 'node:assert/strict';
import { distinctInStockVendorCount } from './vendor-count.ts';

test('vendor-count: three in-stock frags from one shop count as 1 vendor', () => {
  // The populated-arm regression (CTK-187): the eyebrow read the listing-ROW
  // count, so one shop with three in-stock frags printed "3 VENDORS".
  const listings = [
    { inStock: true, vendorSlug: 'jason-fox' },
    { inStock: true, vendorSlug: 'jason-fox' },
    { inStock: true, vendorSlug: 'jason-fox' },
  ];
  assert.equal(distinctInStockVendorCount(listings), 1);
});

test('vendor-count: OOS rows are excluded (the ?include-oos=1 toggle guard)', () => {
  // Would FAIL if the inStock filter were dropped: a raw distinct-vendor count
  // over this mix returns 2, the Tier-1B over-report this helper exists to kill.
  const listings = [
    { inStock: true, vendorSlug: 'cornbred' },
    { inStock: false, vendorSlug: 'jason-fox' },
  ];
  assert.equal(distinctInStockVendorCount(listings), 1);
});

test('vendor-count: all-OOS set counts 0 (callers render the state word, not "0 VENDORS")', () => {
  const listings = [
    { inStock: false, vendorSlug: 'jason-fox' },
    { inStock: false, vendorSlug: 'jason-fox' },
  ];
  assert.equal(distinctInStockVendorCount(listings), 0);
});

test('vendor-count: distinct in-stock vendors across shops', () => {
  const listings = [
    { inStock: true, vendorSlug: 'cornbred' },
    { inStock: true, vendorSlug: 'jason-fox' },
    { inStock: false, vendorSlug: 'tsa' },
  ];
  assert.equal(distinctInStockVendorCount(listings), 2);
});

test('vendor-count: empty set counts 0', () => {
  assert.equal(distinctInStockVendorCount([]), 0);
});
