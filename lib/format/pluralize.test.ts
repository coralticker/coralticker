// lib/format/pluralize.test.ts
//
// CTK-130 #10a — count-noun selection with an explicit plural form. Pins the
// exactly-1-is-singular boundary and the multi-word-head case that motivated
// the explicit (not suffix-based) plural arg.
//
// Runs via Node's built-in test runner with native TypeScript type stripping:
//   node --test --experimental-strip-types lib/format/*.test.ts

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { pluralize } from './pluralize.ts';

test('pluralize: singular only at exactly 1', () => {
  assert.equal(pluralize(1, 'CORAL', 'CORALS'), 'CORAL');
});

test('pluralize: 0 and N>1 take the plural', () => {
  assert.equal(pluralize(0, 'CORAL', 'CORALS'), 'CORALS');
  assert.equal(pluralize(2, 'CORAL', 'CORALS'), 'CORALS');
  assert.equal(pluralize(50, 'LISTING', 'LISTINGS'), 'LISTINGS');
});

test('pluralize: multi-word head pluralizes correctly (the +s mangle case)', () => {
  // PRICE DROP → PRICE DROPS, not PRICE DROPSS / PRICE DROP S — the reason the
  // helper takes an explicit plural form instead of appending a suffix.
  assert.equal(pluralize(1, 'PRICE DROP', 'PRICE DROPS'), 'PRICE DROP');
  assert.equal(pluralize(3, 'PRICE DROP', 'PRICE DROPS'), 'PRICE DROPS');
});
