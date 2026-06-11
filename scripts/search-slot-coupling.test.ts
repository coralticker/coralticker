// CTK-130 #3 — coupling pin for the /search ILIKE slot ceremony ↔
// SEARCH_TOKEN_CAP. Same mechanism class as
// scripts/coral-predicate-coupling.test.ts + no-dead-ink-modifiers.test.ts:
// regex over source, because the real invariant lives inside the Neon tagged
// SQL template, which no type checker sees.
//
// Why a pin and not generation: the Neon tagged template can't splice a
// variable predicate count (search.ts header), so each query carries cap fixed
// `${pN}::text IS NULL OR ...` slots, padded by toSlots() and destructured
// per-function. A SEARCH_TOKEN_CAP bump silently drops tokens past the old cap
// unless every slot site moves in lockstep: toSlots' pad list, the PatternSlots
// tuple, three [p1..pN] destructures, AND the SQL slots (2×cap in searchCorals
// — canonical + alias subquery — plus cap each in searchVendors/searchListings).
// This test fails the suite the moment the cap and any slot site disagree.
//
// Runs via Node's built-in test runner with native TypeScript type stripping:
//   node --test --experimental-strip-types scripts/*.test.ts

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const root = join(import.meta.dirname, '..');
const search = readFileSync(join(root, 'lib/queries/search.ts'), 'utf8');
const params = readFileSync(join(root, 'lib/queries/listing-params.ts'), 'utf8');

const capMatch = params.match(/export const SEARCH_TOKEN_CAP = (\d+)/);
assert.ok(capMatch, 'SEARCH_TOKEN_CAP not found in listing-params.ts');
const cap = Number(capMatch[1]);

// Slice an exported declaration's body: from its `export ...` line to the next
// top-level `export ` (or EOF).
function exportSlice(src: string, decl: string): string {
  const start = src.indexOf(decl);
  assert.notEqual(start, -1, `${decl} not found in search.ts`);
  const next = src.indexOf('\nexport ', start + decl.length);
  return src.slice(start, next === -1 ? undefined : next);
}

function countMatches(s: string, re: RegExp): number {
  return (s.match(re) ?? []).length;
}

// Match only real parameterized slots `${pN}::text IS NULL OR` — the `\d`
// excludes the prose `${p}::text` in the invariant-guard comments.
const SLOT_PRED = /\$\{p\d+\}::text IS NULL OR/g;

test('searchCorals carries 2×cap ILIKE slots (canonical + alias subquery)', () => {
  const fn = exportSlice(search, 'export async function searchCorals');
  assert.equal(
    countMatches(fn, SLOT_PRED),
    2 * cap,
    `searchCorals slot count drifted from 2 × SEARCH_TOKEN_CAP (${2 * cap}); ` +
      'a cap change must add/remove canonical AND alias ILIKE slots in lockstep',
  );
});

test('searchVendors carries cap ILIKE slots', () => {
  const fn = exportSlice(search, 'export async function searchVendors');
  assert.equal(countMatches(fn, SLOT_PRED), cap);
});

test('searchListings carries cap ILIKE slots', () => {
  const fn = exportSlice(search, 'export async function searchListings');
  assert.equal(countMatches(fn, SLOT_PRED), cap);
});

test('PatternSlots tuple has exactly cap members', () => {
  const tuple = (() => {
    const start = search.indexOf('type PatternSlots');
    const end = search.indexOf('];', start);
    return search.slice(start, end);
  })();
  assert.equal(
    countMatches(tuple, /string \| null/g),
    cap,
    'PatternSlots arity drifted from SEARCH_TOKEN_CAP',
  );
});

test('toSlots pads exactly cap entries', () => {
  const fn = (() => {
    const start = search.indexOf('function toSlots');
    const end = search.indexOf('\n}', start);
    return search.slice(start, end);
  })();
  assert.equal(
    countMatches(fn, /patterns\[\d+\]/g),
    cap,
    'toSlots pad-list length drifted from SEARCH_TOKEN_CAP',
  );
});

test('each query destructures exactly cap pattern slots', () => {
  const destructures = search.match(/const \[(p\d(?:, p\d)*)\] = toSlots/g) ?? [];
  assert.equal(destructures.length, 3, 'expected 3 toSlots destructures');
  for (const d of destructures) {
    const params = d.match(/p\d/g) ?? [];
    assert.equal(
      params.length,
      cap,
      `a [p1..pN] = toSlots destructure has ${params.length} slots, not ${cap}`,
    );
  }
});
