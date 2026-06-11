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
  clampSearchEcho,
  clampSearchLength,
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

// CTK-130 #7/#8 — shared code-point-safe clamp. The former .slice(0, N) sites
// (parseSearchQuery + the view-side echo) counted UTF-16 units and could split
// a surrogate pair at the cap boundary; clampSearchLength truncates on whole
// code points.

test('clampSearchLength: BMP string truncates at the cap unchanged', () => {
  const long = 'a'.repeat(SEARCH_QUERY_MAX_LENGTH + 10);
  assert.equal(clampSearchLength(long).length, SEARCH_QUERY_MAX_LENGTH);
  assert.equal(clampSearchLength('short'), 'short');
});

test('clampSearchLength: never splits a surrogate pair at the boundary', () => {
  // 𝐀 (U+1D400) is one astral code point = two UTF-16 units. A string of N
  // such glyphs has length 2N in units. .slice(0, N) would cut at unit N,
  // landing mid-pair → a lone surrogate (\uD835). Code-point truncation keeps
  // whole glyphs and never emits a lone surrogate.
  const astral = '𝐀'.repeat(SEARCH_QUERY_MAX_LENGTH + 5);
  const clamped = clampSearchLength(astral);
  // No lone surrogate survives — every code unit pairs up.
  assert.equal(/[\uD800-\uDBFF](?![\uDC00-\uDFFF])/.test(clamped), false);
  assert.equal(/(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/.test(clamped), false);
  // Caps at SEARCH_QUERY_MAX_LENGTH code points (not units).
  assert.equal([...clamped].length, SEARCH_QUERY_MAX_LENGTH);
});

test('parseSearchQuery: surrogate-pair query caps without a lone surrogate', () => {
  const astral = `${'𝐀'.repeat(SEARCH_QUERY_MAX_LENGTH + 5)}`;
  const parsed = parseSearchQuery(astral)!;
  assert.equal(/[\uD800-\uDBFF](?![\uDC00-\uDFFF])/.test(parsed), false);
});

test('clampSearchEcho: raw echo — first array value, trimmed, code-point clamped', () => {
  // Mirrors parseSearchQuery's array guard (first value wins) but echoes RAW,
  // un-normalized text (CTK-058 locked decision).
  assert.equal(clampSearchEcho('  Rainbow BOZO  '), 'Rainbow BOZO'); // un-lowercased
  assert.equal(clampSearchEcho(['first', 'second']), 'first');
  assert.equal(clampSearchEcho(undefined), '');
  assert.equal(clampSearchEcho([]), '');
  const long = 'b'.repeat(SEARCH_QUERY_MAX_LENGTH + 30);
  assert.equal(clampSearchEcho(long).length, SEARCH_QUERY_MAX_LENGTH);
  const astralEcho = clampSearchEcho('𝐀'.repeat(SEARCH_QUERY_MAX_LENGTH + 5));
  assert.equal(/[\uD800-\uDBFF](?![\uDC00-\uDFFF])/.test(astralEcho), false);
});

test('parseIncludeOOS: only literal "1" toggles', () => {
  assert.equal(parseIncludeOOS('1'), true);
  assert.equal(parseIncludeOOS(undefined), false);
  assert.equal(parseIncludeOOS(''), false);
  assert.equal(parseIncludeOOS('true'), false);
  assert.equal(parseIncludeOOS('0'), false);
});

test('duplicate-key arrays: first value wins across all three parsers (CTK-128 fold)', () => {
  // Next.js delivers string[] for ?sort=a&sort=b URLs — the first value
  // must win, matching parseSearchQuery's guard, not silently default.
  assert.equal(parseSort(['price-asc', 'newest']), 'price-asc');
  assert.equal(parseSort(['bogus', 'price-asc']), 'newest'); // first wins, then allowlist
  assert.equal(parseCategory(['lps', 'sps']), 'lps');
  assert.equal(parseIncludeOOS(['1', '0']), true);
  assert.equal(parseIncludeOOS(['0', '1']), false);
  assert.equal(parseIncludeOOS([]), false);
});
