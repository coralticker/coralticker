// Allowlist coverage for the <SortFilterBar> URL-state parsers (CTK-127
// fold #9). Two branches per parser: allowlisted values round-trip; absent /
// tampered inputs fall back to the bare default per canonical-chain
// discipline. Allowlists derive from the label-record keys, so these tests
// also pin the record memberships.
//
// Runs via Node's built-in test runner with native TypeScript type stripping:
//   node --test --experimental-strip-types lib/queries/*.test.ts

import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  CATEGORY_LABELS,
  SORT_LABELS,
  parseCategory,
  parseIncludeOOS,
  parseSort,
} from './listing-params.ts';

test('parseSort: every allowlisted value round-trips', () => {
  for (const value of Object.keys(SORT_LABELS)) {
    assert.equal(parseSort(value), value);
  }
});

test('parseSort: absent + tampered inputs fall back to newest', () => {
  assert.equal(parseSort(undefined), 'newest');
  assert.equal(parseSort(''), 'newest');
  assert.equal(parseSort('price'), 'newest');
  assert.equal(parseSort('PRICE-ASC'), 'newest'); // case-sensitive by design
  assert.equal(parseSort('price-asc;DROP TABLE'), 'newest');
});

test('parseCategory: every allowlisted value round-trips', () => {
  for (const value of Object.keys(CATEGORY_LABELS)) {
    assert.equal(parseCategory(value), value);
  }
});

test('parseCategory: absent + tampered + UI-hidden inputs fall back to null', () => {
  assert.equal(parseCategory(undefined), null);
  assert.equal(parseCategory(''), null);
  assert.equal(parseCategory('SPS'), null); // case-sensitive by design
  assert.equal(parseCategory('acropora'), null);
  // Schema-enum tail excluded from the filter UI (fish / invert / equipment
  // / other) — allowlist rejects them even though the DB column allows them.
  assert.equal(parseCategory('fish'), null);
  assert.equal(parseCategory('other'), null);
});

test('parseCategory: label record carries the 8 locked chips in display order', () => {
  assert.deepEqual(Object.keys(CATEGORY_LABELS), [
    'lps',
    'sps',
    'zoa',
    'mushroom',
    'chalice',
    'clam',
    'anemone',
    'softie',
  ]);
});

test('parseIncludeOOS: only literal "1" toggles', () => {
  assert.equal(parseIncludeOOS('1'), true);
  assert.equal(parseIncludeOOS(undefined), false);
  assert.equal(parseIncludeOOS(''), false);
  assert.equal(parseIncludeOOS('true'), false);
  assert.equal(parseIncludeOOS('0'), false);
});
