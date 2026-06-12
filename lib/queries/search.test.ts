// The builder lives in listing-params.ts (pure parser family; search.ts carries
// a DB import chain the bare node test runner can't load).

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { SEARCH_TOKEN_CAP, buildIlikePatterns } from './listing-params.ts';

test('buildIlikePatterns: tokens wrap as %tok% per whitespace split', () => {
  assert.deepEqual(buildIlikePatterns('homewrecker'), ['%homewrecker%']);
  assert.deepEqual(buildIlikePatterns('rainbow tenuis'), [
    '%rainbow%',
    '%tenuis%',
  ]);
});

test('buildIlikePatterns: caps at SEARCH_TOKEN_CAP, drops the remainder', () => {
  const tokens = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'];
  const patterns = buildIlikePatterns(tokens.join(' '));
  assert.equal(patterns.length, SEARCH_TOKEN_CAP);
  assert.deepEqual(
    patterns,
    tokens.slice(0, SEARCH_TOKEN_CAP).map((t) => `%${t}%`),
  );
});

test('buildIlikePatterns: escapes % _ ! with the ! escape char', () => {
  // JS template cooking collapses backslash escapes, hence '!' as the escape
  // char — and '!' itself must escape so a literal '!' in a query can't
  // orphan-escape what follows.
  assert.deepEqual(buildIlikePatterns('50%'), ['%50!%%']);
  assert.deepEqual(buildIlikePatterns('a_b'), ['%a!_b%']);
  assert.deepEqual(buildIlikePatterns('wow!'), ['%wow!!%']);
  assert.deepEqual(buildIlikePatterns('50%_off!'), ['%50!%!_off!!%']);
});

test('buildIlikePatterns: empty input yields no patterns', () => {
  // parseSearchQuery returns null before this point; the helper-side [] is
  // the second guard (search.ts helpers return empty results, never an
  // unfiltered all-true predicate set).
  assert.deepEqual(buildIlikePatterns(''), []);
});
