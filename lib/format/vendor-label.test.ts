import { test } from 'node:test';
import assert from 'node:assert/strict';
import { vendorShorthand } from './vendor-label.ts';

test('vendorShorthand: canon end-label map (/brand-manager 2026-06-21)', () => {
  assert.equal(vendorShorthand('wwc', 'World Wide Corals'), 'WWC');
  assert.equal(vendorShorthand('jf', 'Jason Fox Signature Corals'), 'JF');
  assert.equal(vendorShorthand('tsa', 'Top Shelf Aquatics'), 'TSA');
  assert.equal(vendorShorthand('pacific_east', 'Pacific East Aquaculture'), 'PEA');
  assert.equal(vendorShorthand('poto', 'Pieces of the Ocean'), 'POTO');
  assert.equal(vendorShorthand('vivid_aquariums', 'Vivid Aquariums'), 'Vivid');
  assert.equal(vendorShorthand('aquasd', 'Aqua SD'), 'Aqua SD');
  // R2R-native abbreviation on the space-constrained chart surface:
  assert.equal(vendorShorthand('unique_corals', 'Unique Corals'), 'UC');
  assert.equal(vendorShorthand('tidal_gardens', 'Tidal Gardens'), 'TG');
  assert.equal(vendorShorthand('cornbred', 'Cornbred Corals'), 'Cornbred');
  // Canon-full (short forms overloaded in the community):
  assert.equal(vendorShorthand('battlecorals', 'Battlecorals'), 'Battlecorals');
  assert.equal(vendorShorthand('reef_chasers', 'Reef Chasers'), 'Reef Chasers');
  assert.equal(vendorShorthand('reefnbid', 'ReefnBid'), 'ReefnBid');
});

test('vendorShorthand: un-canon vendor → full display_name, never an invented abbreviation', () => {
  // A future scraper add not yet in the canon table renders its full name.
  assert.equal(vendorShorthand('some_new_vendor', 'Some New Vendor'), 'Some New Vendor');
});
