import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  bucketTransition,
  bucketLabel,
  buildBucketedRows,
  DIVIDER_THRESHOLD,
} from './group-bucket.ts';

// Mirrors the view-side gate (12-card threshold + bucketTransition between
// adjacent cards) so the divider count tracks production.
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

test('bucketLabel: dayDiff=0 same-day → null (totality, CTK-130)', () => {
  // Same-day returns null (no divider) under the base no-Today-header rule.
  // bucketTransition() still skips same-day pairs for inter-row transitions;
  // the leading caller relies on this null.
  const now = new Date(2026, 4, 14, 12, 0);
  const sameDay = new Date(2026, 4, 14, 9, 0).toISOString();
  assert.equal(bucketLabel(sameDay, now), null);
});

test('bucketLabel: future-dated row (dayDiff<0) → null (clock-skew suppression)', () => {
  // A top row ahead of now under midnight Neon-vs-Vercel skew — suppressed,
  // not mislabelled. buildBucketedRows leans on this for the leading divider.
  const now = new Date(2026, 4, 14, 12, 0);
  const future = new Date(2026, 4, 15, 9, 0).toISOString();
  assert.equal(bucketLabel(future, now), null);
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

// --- Threshold + transition boundary cases ---------------------------------

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

// --- buildBucketedRows -----------------------------------------------------
// Rows are bare timestamp strings here; getTimestamp = identity.

const id = (t: string) => t;

test('buildBucketedRows: today-top feed → NO leading label (base no-Today rule)', () => {
  // Top bucket is today (same local day as now) → leading label suppressed;
  // this is the unfiltered-feed parity case (/new, /deals on a normal day).
  const now = new Date(2026, 4, 14, 12, 0);
  const rows = [
    new Date(2026, 4, 14, 11, 0).toISOString(), // today
    new Date(2026, 4, 14, 9, 0).toISOString(), // today
    new Date(2026, 4, 13, 20, 0).toISOString(), // yesterday → transition here
  ];
  const out = buildBucketedRows(rows, id, now);
  assert.equal(out[0]!.label, null); // no leading label
  assert.equal(out[1]!.label, null); // same-day, no transition
  assert.equal(out[2]!.label, 'YESTERDAY'); // inter-row transition
});

test('buildBucketedRows: past-top feed → leading label renders (filtered/slow-day case)', () => {
  // Top bucket is days old (a filtered /search feed, or a slow-day unfiltered
  // /new) → the leading label renders per the carve-out.
  const now = new Date(2026, 4, 14, 12, 0);
  const rows = [
    new Date(2026, 4, 11, 11, 0).toISOString(), // 3 days ago (top)
    new Date(2026, 4, 11, 9, 0).toISOString(), // same bucket
    new Date(2026, 4, 9, 9, 0).toISOString(), // 5 days ago → transition
  ];
  const out = buildBucketedRows(rows, id, now);
  assert.equal(out[0]!.label, '3 DAYS AGO'); // leading label present
  assert.equal(out[1]!.label, null);
  assert.equal(out[2]!.label, '5 DAYS AGO');
});

test('buildBucketedRows: future-dated top row → leading label suppressed (clock skew)', () => {
  // Different local day AND ahead of now → bucketTransition fires but
  // bucketLabel totality returns null, so no leading divider (no throw).
  const now = new Date(2026, 4, 14, 12, 0);
  const rows = [
    new Date(2026, 4, 15, 1, 0).toISOString(), // tomorrow (skew)
    new Date(2026, 4, 14, 9, 0).toISOString(), // today
  ];
  const out = buildBucketedRows(rows, id, now);
  assert.equal(out[0]!.label, null);
  assert.equal(out[1]!.label, null); // future→today is a different-day pair,
  // but the label keys on the CURR (today) vs now → same day → null.
});

test('buildBucketedRows: yesterday-top feed → leading YESTERDAY label', () => {
  const now = new Date(2026, 4, 14, 12, 0);
  const rows = [
    new Date(2026, 4, 13, 22, 0).toISOString(), // yesterday (top)
    new Date(2026, 4, 13, 8, 0).toISOString(), // same bucket
  ];
  const out = buildBucketedRows(rows, id, now);
  assert.equal(out[0]!.label, 'YESTERDAY');
  assert.equal(out[1]!.label, null);
});

test('buildBucketedRows: getTimestamp selects the surface ordering field', () => {
  // Mirrors the real call shape — rows are objects, getTimestamp picks the
  // per-surface field (eventAt / observedAt / firstSeenAt).
  const now = new Date(2026, 4, 14, 12, 0);
  const rows = [
    { id: 1, ts: new Date(2026, 4, 12, 10, 0).toISOString() }, // 2 days ago top
    { id: 2, ts: new Date(2026, 4, 12, 9, 0).toISOString() },
  ];
  const out = buildBucketedRows(rows, (r) => r.ts, now);
  assert.equal(out[0]!.label, '2 DAYS AGO');
  assert.equal(out[0]!.row.id, 1); // row passes through unchanged
  assert.equal(out[1]!.label, null);
});

test('buildBucketedRows: empty feed → empty annotation list', () => {
  const now = new Date(2026, 4, 14, 12, 0);
  assert.deepEqual(buildBucketedRows([], id, now), []);
});
