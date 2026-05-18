// lib/format/relative-time.test.ts
//
// Singular-boundary tests per site.md §3.6 fold-point A.
// Captures /lead-frontend's commitment from 2026-05-01 brief — proves
// the ladder emits "1 minute ago" not "1 minutes ago" at the boundaries.
//
// Runs via Node's built-in test runner with native TypeScript type stripping
// (Node v22.6+; stable from v23.6 unflagged): `node --test lib/format/*.test.ts`.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { formatRelativeTime } from './relative-time.ts';

const NOW = new Date('2026-05-14T12:00:00Z');

test('60s boundary → "1 minute ago" singular', () => {
  const past = new Date(NOW.getTime() - 60_000).toISOString();
  assert.equal(formatRelativeTime(past, NOW), '1 minute ago');
});

test('3600s boundary → "1 hour ago" singular', () => {
  const past = new Date(NOW.getTime() - 3_600_000).toISOString();
  assert.equal(formatRelativeTime(past, NOW), '1 hour ago');
});

test('86400s boundary → "1 day ago" singular', () => {
  const past = new Date(NOW.getTime() - 86_400_000).toISOString();
  assert.equal(formatRelativeTime(past, NOW), '1 day ago');
});

test('604800s boundary → MMM D absolute format (< 7d → ≥ 7d transition)', () => {
  const past = new Date(NOW.getTime() - 604_800_000).toISOString();
  const result = formatRelativeTime(past, NOW);
  assert.match(result, /^[A-Z][a-z]{2} \d{1,2}$/, `expected "MMM D" pattern, got "${result}"`);
});
