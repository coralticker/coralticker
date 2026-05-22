// lib/format/lineage.test.ts
//
// Branch coverage for formatLineage() — the plain-string lineage formatter
// consumed by <ListingCard>'s Lineage field per site.md §3.5.1.
//
// Lands per CTK-062 Session 4c F-9 fold-inline batch. Absorbs the four
// formatLineage branch cases scoped at CTK-076 (both-null, origin-only,
// year-only, both-present) plus the empty-string-on-both-null contract pin —
// the contract is currently silent at the type level (return type `string`
// doesn't telegraph the empty case); this test IS the contract.
//
// Runs via Node's built-in test runner with native TypeScript type stripping:
//   node --test --experimental-strip-types lib/format/*.test.ts

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { formatLineage } from './lineage.ts';

test('formatLineage: both fields present → "vendor · year"', () => {
  assert.equal(
    formatLineage({ origin_vendor: 'Jason Fox', year_introduced: 2018 }),
    'Jason Fox · 2018',
  );
});

test('formatLineage: origin-only → vendor', () => {
  assert.equal(
    formatLineage({ origin_vendor: 'Jason Fox', year_introduced: null }),
    'Jason Fox',
  );
});

test('formatLineage: year-only → year', () => {
  assert.equal(
    formatLineage({ origin_vendor: null, year_introduced: 2018 }),
    '2018',
  );
});

test('formatLineage: both-null → empty string (contract pin)', () => {
  // Caller (app/coral/[slug]/page.tsx buildLineageFields) handles the empty
  // case via NULL-drop discipline. Empty-string contract is intentional —
  // type signature stays `string` rather than `string | null` to avoid
  // rippling Optional-handling into every consumer.
  assert.equal(
    formatLineage({ origin_vendor: null, year_introduced: null }),
    '',
  );
});
