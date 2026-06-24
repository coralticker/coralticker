import { test } from 'node:test';
import assert from 'node:assert/strict';
import { marketLineState } from './market-line-state.ts';

test('market-line-state: buyable price → available', () => {
  assert.equal(
    marketLineState({ inStockVendorCount: 2, isAllOOS: false, hasBuyablePrice: true }),
    'available',
  );
});

test('market-line-state: in-stock but no buyable price → price-on-request, NOT all-oos', () => {
  // The reachable Tier-1B path (CTK-187 /code-review #1A): in_stock=true,
  // current_price=null. Would FAIL if the OOS-with-history branch printed
  // ALL OUT OF STOCK for an inStockVendorCount>0 input.
  const state = marketLineState({
    inStockVendorCount: 1,
    isAllOOS: false,
    hasBuyablePrice: false,
  });
  assert.equal(state, 'price-on-request');
  assert.notEqual(state, 'all-oos');
});

test('market-line-state: 0 in-stock + no in-window carriers → not-listed, NOT all-oos', () => {
  // Path 1B: 8+ days stale, non-thin 90-day envelope. isAllOOS is false
  // (inWindowVendorCount uses the 7-day recency window). Would FAIL if the
  // branch printed ALL OUT OF STOCK for a !isAllOOS input.
  const state = marketLineState({
    inStockVendorCount: 0,
    isAllOOS: false,
    hasBuyablePrice: false,
  });
  assert.equal(state, 'not-listed');
  assert.notEqual(state, 'all-oos');
});

test('market-line-state: 0 in-stock + in-window carriers → all-oos', () => {
  assert.equal(
    marketLineState({ inStockVendorCount: 0, isAllOOS: true, hasBuyablePrice: false }),
    'all-oos',
  );
});

test('market-line-state: in-stock vendor takes priority over isAllOOS=false bookkeeping', () => {
  // Belt-and-suspenders: a price-on-request coral is never not-listed even
  // though both have isAllOOS=false — the inStockVendorCount check fires first.
  assert.equal(
    marketLineState({ inStockVendorCount: 3, isAllOOS: false, hasBuyablePrice: false }),
    'price-on-request',
  );
});
