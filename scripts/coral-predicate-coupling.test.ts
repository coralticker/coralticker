// CTK-128 (a) + (d) — source-level coupling pins for the /corals index ↔
// /coral/[slug] destination pair, same mechanism class as
// scripts/no-dead-ink-modifiers.test.ts (regex over source because the real
// invariants live in SQL template literals and Next segment config, which
// no type checker sees).
//
// Two invariant families:
//   1. Cadence tandem (d): the /corals page revalidate literal must equal
//      CORALS_INDEX_REVALIDATE_S — Next statically analyzes segment config,
//      so the page side can't import the constant; this test is the
//      mechanical coupling the paired comments alone don't give.
//   2. Predicate coupling (a): the index lateral and getCoralAvailability
//      share the core triple (named_coral_id + recency window + in_stock
//      default) BY CONVENTION, with two deliberate asymmetries that must
//      point the right way: vendor guards index-side ONLY (destination-side
//      is CTK-125, trigger-gated), toggle OR destination-side ONLY
//      (Default-render parity rule). A shared SQL helper was rejected at
//      CTK-128 (a) — it would hide exactly these asymmetries.
//
// Runs via Node's built-in test runner with native TypeScript type stripping:
//   node --test --experimental-strip-types scripts/*.test.ts

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const root = join(import.meta.dirname, '..');
const namedCorals = readFileSync(
  join(root, 'lib/queries/named-corals.ts'),
  'utf8',
);
const listings = readFileSync(join(root, 'lib/queries/listings.ts'), 'utf8');
const coralsPage = readFileSync(join(root, 'app/corals/page.tsx'), 'utf8');

// Slice getCoralAvailability's body so asymmetry checks don't false-match
// against getVendorInventory (which legitimately carries the toggle OR) or
// future siblings.
const availabilityFn = (() => {
  const start = listings.indexOf('export async function getCoralAvailability');
  assert.notEqual(start, -1, 'getCoralAvailability not found in listings.ts');
  const end = listings.indexOf('export async function', start + 1);
  return listings.slice(start, end === -1 ? undefined : end);
})();

test('cadence tandem: /corals page revalidate literal equals CORALS_INDEX_REVALIDATE_S', () => {
  const constMatch = namedCorals.match(
    /export const CORALS_INDEX_REVALIDATE_S = (\d+)/,
  );
  assert.ok(constMatch, 'CORALS_INDEX_REVALIDATE_S not found in named-corals.ts');
  const pageMatch = coralsPage.match(/^export const revalidate = (\d+);/m);
  assert.ok(pageMatch, 'page revalidate literal not found in app/corals/page.tsx');
  assert.equal(
    pageMatch[1],
    constMatch[1],
    'app/corals/page.tsx revalidate literal drifted from CORALS_INDEX_REVALIDATE_S — retune them in tandem (CTK-128 (d))',
  );
});

test('cadence tandem: the index unstable_cache consumes the constant, not a literal', () => {
  assert.ok(
    /revalidate: CORALS_INDEX_REVALIDATE_S/.test(namedCorals),
    'getAllNamedCoralsWithListings unstable_cache no longer reads CORALS_INDEX_REVALIDATE_S',
  );
});

test('predicate coupling: both sides window on CORAL_RECENCY_DAYS', () => {
  assert.ok(
    /CORAL_RECENCY_DAYS/.test(namedCorals),
    'named-corals.ts lost its CORAL_RECENCY_DAYS reference',
  );
  assert.ok(
    /CORAL_RECENCY_DAYS/.test(availabilityFn),
    'getCoralAvailability lost its CORAL_RECENCY_DAYS reference',
  );
});

test('predicate coupling: index lateral carries the in_stock gate', () => {
  assert.ok(
    /vl\.in_stock = true/.test(namedCorals),
    "index lateral lost 'vl.in_stock = true' — Default-render parity gate (branding-guide §State markers)",
  );
});

test('asymmetry 1: vendor guards are index-side ONLY (destination-side is CTK-125)', () => {
  assert.ok(
    /v\.active = true/.test(namedCorals),
    'index lateral lost the v.active vendor guard',
  );
  assert.ok(
    /NOT LIKE '!_%' ESCAPE '!'/.test(namedCorals),
    'index lateral lost the sentinel-slug vendor guard',
  );
  assert.ok(
    !/v\.active/.test(availabilityFn),
    'getCoralAvailability gained a vendor guard — that predicate change belongs to CTK-125; if CTK-125 fired, update this pin AND getCoralInWindowVendorCount together',
  );
});

test('asymmetry 2: the includeOOS toggle OR is destination-side ONLY', () => {
  assert.ok(
    /::boolean OR vl\.in_stock = true/.test(availabilityFn),
    'getCoralAvailability lost the includeOOS OR predicate',
  );
  assert.ok(
    !/::boolean OR/.test(namedCorals),
    'index lateral gained a toggle OR — parity is measured against the destination DEFAULT render, never the toggled view',
  );
});
