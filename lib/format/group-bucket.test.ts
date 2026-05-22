// lib/format/group-bucket.test.ts
//
// Boundary tests for bucketTransition() + bucketLabel() and the 12-card
// threshold gate logic per site.md §4.4 + branding-guide.md §"Group dividers"
// line 257. Threshold gate is view-side (app/new/page.tsx); these tests
// exercise the pure helpers + simulate the gate to confirm the divider count
// the view emits matches spec at each boundary.
//
// Runs via Node's built-in test runner with native TypeScript type stripping:
//   node --test --experimental-strip-types lib/format/*.test.ts

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { bucketTransition, bucketLabel } from './group-bucket.ts';

const DIVIDER_THRESHOLD = 12;

// Helper: simulates the view-side dividers-fired count for a feed of N cards
// with given event_at timestamps. Mirrors app/new/page.tsx FeedWithDividers
// logic (12-card threshold gate + bucketTransition between adjacent cards).
function dividersFired(eventAts: string[]): number {
  if (eventAts.length < DIVIDER_THRESHOLD) return 0;
  let count = 0;
  for (let i = 1; i < eventAts.length; i++) {
    if (bucketTransition(eventAts[i - 1]!, eventAts[i]!)) count++;
  }
  return count;
}

// Build N timestamps inside a single local-day (today at noon-ish — stable).
function sameDayTimestamps(n: number): string[] {
  return Array.from({ length: n }, (_, i) =>
    new Date(2026, 4, 14, 12, n - i).toISOString(),
  );
}

// Build N timestamps split across today (recent) and yesterday (older).
// Order recent-first per /new ORDER BY event_at DESC.
function twoDaySplit(todayCount: number, yesterdayCount: number): string[] {
  const out: string[] = [];
  for (let i = 0; i < todayCount; i++) {
    out.push(new Date(2026, 4, 14, 10, todayCount - i).toISOString());
  }
  for (let i = 0; i < yesterdayCount; i++) {
    out.push(new Date(2026, 4, 13, 20, yesterdayCount - i).toISOString());
  }
  return out;
}

// --- bucketTransition: same-day vs. cross-day -------------------------------

test('bucketTransition: same local day → false', () => {
  const a = new Date(2026, 4, 14, 9, 0).toISOString();
  const b = new Date(2026, 4, 14, 23, 59).toISOString();
  assert.equal(bucketTransition(a, b), false);
});

test('bucketTransition: crosses local-day boundary → true', () => {
  const today = new Date(2026, 4, 14, 0, 5).toISOString();
  const yesterday = new Date(2026, 4, 13, 23, 55).toISOString();
  assert.equal(bucketTransition(today, yesterday), true);
});

// --- bucketLabel ladder ---------------------------------------------------

test('bucketLabel: dayDiff=0 same-day → throws (caller contract)', () => {
  // Per CTK-062 F-7: same-day passthrough is a caller bug — bucketTransition()
  // skips same-day pairs, so bucketLabel() should never receive dayDiff=0.
  const now = new Date(2026, 4, 14, 12, 0);
  const sameDay = new Date(2026, 4, 14, 9, 0).toISOString();
  assert.throws(() => bucketLabel(sameDay, now), /dayDiff must be positive/);
});

test('bucketLabel: 1 day ago → YESTERDAY', () => {
  const now = new Date(2026, 4, 14, 12, 0);
  const yesterday = new Date(2026, 4, 13, 18, 0).toISOString();
  assert.equal(bucketLabel(yesterday, now), 'YESTERDAY');
});

test('bucketLabel: 3 days ago → "3 DAYS AGO"', () => {
  const now = new Date(2026, 4, 14, 12, 0);
  const past = new Date(2026, 4, 11, 12, 0).toISOString();
  assert.equal(bucketLabel(past, now), '3 DAYS AGO');
});

test('bucketLabel: 8 days ago → MMM D uppercase', () => {
  const now = new Date(2026, 4, 14, 12, 0);
  const past = new Date(2026, 4, 6, 12, 0).toISOString();
  assert.equal(bucketLabel(past, now), 'MAY 6');
});

// --- Threshold + transition boundary cases per directive ------------------

test('exactly 12 cards spanning two days → divider fires once', () => {
  // 11 today + 1 yesterday = 12 total, one bucket transition at index 11.
  const feed = twoDaySplit(11, 1);
  assert.equal(feed.length, 12);
  assert.equal(dividersFired(feed), 1);
});

test('11 cards spanning two days → no divider (under threshold)', () => {
  // 10 today + 1 yesterday = 11 total; under DIVIDER_THRESHOLD so the
  // view-side gate suppresses all dividers regardless of transitions.
  const feed = twoDaySplit(10, 1);
  assert.equal(feed.length, 11);
  assert.equal(dividersFired(feed), 0);
});

test('13 cards same-day → no divider (no transition)', () => {
  // 13 same-day cards; over threshold but bucketTransition() always false.
  const feed = sameDayTimestamps(13);
  assert.equal(feed.length, 13);
  assert.equal(dividersFired(feed), 0);
});

test('12 cards spanning two days (6 + 6) → divider fires once', () => {
  // Equal split — divider lands at index 6 where the two-day transition is.
  const feed = twoDaySplit(6, 6);
  assert.equal(feed.length, 12);
  assert.equal(dividersFired(feed), 1);
});

test('5 cards spanning two days → no divider (under threshold)', () => {
  // 3 today + 2 yesterday = 5; under DIVIDER_THRESHOLD, gate suppresses.
  const feed = twoDaySplit(3, 2);
  assert.equal(feed.length, 5);
  assert.equal(dividersFired(feed), 0);
});
