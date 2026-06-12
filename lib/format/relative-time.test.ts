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

test('future timestamp (SSR/client clock skew) → clamps to "1 minute ago"', () => {
  // Negative diffs clamp to 0 + minute-floor clamps to 1. Without these clamps
  // a clock-skewed future timestamp would render "0 minutes ago" or a negative
  // count.
  const future = new Date(NOW.getTime() + 30_000).toISOString();
  assert.equal(formatRelativeTime(future, NOW), '1 minute ago');
});
