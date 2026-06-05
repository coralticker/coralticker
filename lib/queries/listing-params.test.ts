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
  SEARCH_QUERY_MAX_LENGTH,
  SORT_LABELS,
  parseCategory,
  parseIncludeOOS,
  parseSearchQuery,
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

// CTK-058 D-058-4 — /search query normalizer. Mirror cases against the §3.3
// runtime rules the stored normalized_title/normalized_name were built with.

test('parseSearchQuery: plain query round-trips lowercased', () => {
  assert.equal(parseSearchQuery('homewrecker'), 'homewrecker');
  assert.equal(parseSearchQuery('JF Homewrecker'), 'jf homewrecker');
});

test('parseSearchQuery: whitespace trims + collapses', () => {
  assert.equal(parseSearchQuery('  rainbow   tenuis '), 'rainbow tenuis');
  assert.equal(parseSearchQuery('rainbow\ttenuis\n'), 'rainbow tenuis');
});

test('parseSearchQuery: accents normalize per §3.3 unaccent (NFKD + strip marks)', () => {
  // An accent-bearing query must reach the same form as the unaccented
  // stored normalized_title or the match silently misses.
  assert.equal(parseSearchQuery('café'), 'cafe');
  assert.equal(parseSearchQuery('AÇAN LORD'), 'acan lord');
  assert.equal(parseSearchQuery('tÉnuis'), 'tenuis');
});

test('parseSearchQuery: empty / missing / whitespace-only fall back to null', () => {
  assert.equal(parseSearchQuery(undefined), null);
  assert.equal(parseSearchQuery(''), null);
  assert.equal(parseSearchQuery('   '), null);
  assert.equal(parseSearchQuery('\t\n'), null);
});

test('parseSearchQuery: array input (duplicate ?q= keys) takes the first value', () => {
  // Next.js delivers string[] on ?q=a&q=b — guard per /code-review fold #1;
  // pre-guard code threw in generateMetadata + the page body (500).
  assert.equal(parseSearchQuery(['a', 'b']), 'a');
  assert.equal(parseSearchQuery([]), null);
  assert.equal(parseSearchQuery(['', 'b']), null);
});

test('parseSearchQuery: caps at SEARCH_QUERY_MAX_LENGTH post-normalization', () => {
  const long = 'a'.repeat(SEARCH_QUERY_MAX_LENGTH + 40);
  assert.equal(parseSearchQuery(long)?.length, SEARCH_QUERY_MAX_LENGTH);
  // Cap counts normalized characters — pre-collapse padding doesn't consume it.
  const padded = `${'  '.repeat(10)}rainbow tenuis`;
  assert.equal(parseSearchQuery(padded), 'rainbow tenuis');
});

test('parseSearchQuery: SQL metacharacters pass through for the pattern-builder to escape', () => {
  // Escaping is buildIlikePatterns' job (lib/queries/search.ts) — the parser
  // must not strip or double-handle % / _ / !.
  assert.equal(parseSearchQuery('50%_off!'), '50%_off!');
});

test('parseIncludeOOS: only literal "1" toggles', () => {
  assert.equal(parseIncludeOOS('1'), true);
  assert.equal(parseIncludeOOS(undefined), false);
  assert.equal(parseIncludeOOS(''), false);
  assert.equal(parseIncludeOOS('true'), false);
  assert.equal(parseIncludeOOS('0'), false);
});
