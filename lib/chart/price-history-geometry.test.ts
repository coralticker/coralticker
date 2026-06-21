import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  groupByVendor,
  computeDomain,
  xScale,
  yScale,
  dailyStepGeometry,
  floorGeometry,
  vendorLineGeometry,
  endLabels,
  viewboxWidth,
  estimateLabelWidth,
  xTicks,
  isThinHistory,
  thinObservation,
  niceTicksWithin,
  FRAME,
} from './price-history-geometry.ts';
import type {
  CoralVendorPricePoint,
  CoralEnvelopePoint,
} from '@/lib/queries/coral-price';

// ── helpers ──────────────────────────────────────────────────────────────────
function vp(
  vendorId: number,
  vendorSlug: string,
  day: string,
  minPrice: number,
  listingCount = 1,
): CoralVendorPricePoint {
  return { vendorId, vendorSlug, day, minPrice, listingCount };
}
function env(day: string, minPrice: number): CoralEnvelopePoint {
  return { day, minPrice };
}
// Identity label resolver for tests (the page injects vendorShorthand).
const upper = (slug: string) => slug.toUpperCase();

// ── grouping ─────────────────────────────────────────────────────────────────
test('groupByVendor: one track per vendor, points day-sorted, stable order', () => {
  const tracks = groupByVendor([
    vp(20, 'tsa', '2026-05-02', 650),
    vp(10, 'wwc', '2026-05-03', 680),
    vp(20, 'tsa', '2026-05-01', 700), // out of order
    vp(10, 'wwc', '2026-05-01', 720),
  ]);
  assert.equal(tracks.length, 2);
  assert.deepEqual(tracks.map((t) => t.vendorId), [10, 20]); // sorted by vendorId
  assert.deepEqual(tracks[0]!.points.map((p) => p.minPrice), [720, 680]); // wwc, day-ordered
});

// ── scales + y-fit ───────────────────────────────────────────────────────────
test('xScale/yScale: domain endpoints map to plot edges', () => {
  const e = [env('2026-03-01', 600), env('2026-06-01', 700)];
  const now = Date.parse('2026-06-01T00:00:00Z');
  const d = computeDomain(e, [], now);
  assert.equal(Math.round(xScale(d.t1, d)), FRAME.plotRight);
  assert.equal(Math.round(yScale(d.yMax, d)), FRAME.plotTop);
  assert.equal(Math.round(yScale(d.yMin, d)), FRAME.plotBottom);
});

test('computeDomain: y-axis fits the data range — no dead space above the top', () => {
  // data max 510 — the old niceMax-ceil would push the top to 600 (90 of dead
  // space). The fitted axis keeps yMax within a small pad of the data max.
  const e = [env('2026-05-01', 300), env('2026-06-01', 510)];
  const now = Date.parse('2026-06-01T00:00:00Z');
  const d = computeDomain(e, [], now);
  assert.ok(d.yMax < 510 * 1.1, `yMax ${d.yMax} should hug the data max, not ceil to 600`);
  assert.ok(d.yMax >= 510); // still above the data so the top line isn't clipped
  // every gridline sits inside the rendered range
  for (const t of d.yTicks) {
    assert.ok(t >= d.yMin - 1e-6 && t <= d.yMax + 1e-6);
  }
});

test('computeDomain: t1 is now even when the last data day is earlier', () => {
  const e = [env('2026-05-01', 600), env('2026-05-10', 620)];
  const now = Date.parse('2026-06-01T00:00:00Z'); // 22 days after last data
  const d = computeDomain(e, [], now);
  assert.equal(d.t1, now);
});

// ── daily-series step geometry ───────────────────────────────────────────────
test('dailyStepGeometry: a multi-day gap splits into separate paths', () => {
  const pts = [
    { day: '2026-05-01', value: 700 },
    { day: '2026-05-02', value: 680 },
    // gap 05-03..05-09
    { day: '2026-05-10', value: 690 },
    { day: '2026-05-11', value: 690 },
  ];
  const now = Date.parse('2026-05-11T00:00:00Z');
  const d = computeDomain([env('2026-05-01', 700), env('2026-05-11', 690)], [], now);
  const g = dailyStepGeometry(pts, d);
  assert.equal(g.paths.length, 2);
  assert.equal(g.dots.length, 0);
});

test('dailyStepGeometry: an isolated single-day run becomes a dot, not an invisible path', () => {
  const pts = [
    { day: '2026-05-01', value: 700 },
    // gap
    { day: '2026-05-20', value: 650 }, // isolated single day
  ];
  const now = Date.parse('2026-05-20T00:00:00Z');
  const d = computeDomain([env('2026-05-01', 700), env('2026-05-20', 650)], [], now);
  const g = dailyStepGeometry(pts, d);
  assert.equal(g.paths.length, 0); // neither run has ≥2 contiguous days
  assert.equal(g.dots.length, 2);
});

test('floorGeometry + vendorLineGeometry: both share the gap-break rule', () => {
  const now = Date.parse('2026-05-05T00:00:00Z');
  const e = [env('2026-05-01', 600), env('2026-05-02', 600), env('2026-05-03', 590)];
  const track = groupByVendor([
    vp(10, 'wwc', '2026-05-01', 620),
    vp(10, 'wwc', '2026-05-02', 620),
    vp(10, 'wwc', '2026-05-03', 610),
  ])[0]!;
  const d = computeDomain(e, [track], now);
  assert.equal(floorGeometry(e, d).paths.length, 1);
  assert.equal(vendorLineGeometry(track, d).paths.length, 1);
});

// ── end-labels ───────────────────────────────────────────────────────────────
test('endLabels: one per vendor at its last day, labelFor injected, de-collided', () => {
  const tracks = groupByVendor([
    vp(10, 'wwc', '2026-05-20', 680),
    vp(20, 'tsa', '2026-05-20', 681), // nearly identical y
  ]);
  const now = Date.parse('2026-05-25T00:00:00Z');
  const d = computeDomain([], tracks, now);
  const labels = endLabels(tracks, d, upper);
  assert.equal(labels.length, 2);
  assert.ok(Math.abs(labels[1]!.y - labels[0]!.y) >= 13); // pushed apart
  assert.deepEqual(labels.map((l) => l.text).sort(), ['TSA', 'WWC']);
});

test('endLabels: OOS vendor label sits at its last in-stock day (mid-plot), not the right edge', () => {
  const tracks = groupByVendor([
    vp(10, 'wwc', '2026-05-01', 680),
    vp(10, 'wwc', '2026-05-05', 680), // last day = 05-05, then nothing (OOS)
  ]);
  const now = Date.parse('2026-05-25T00:00:00Z'); // 20 days later
  const d = computeDomain([], tracks, now);
  const labels = endLabels(tracks, d, upper);
  assert.equal(labels.length, 1);
  assert.ok(labels[0]!.x < FRAME.plotRight, 'OOS label should not reach the right edge');
});

test('viewboxWidth: reserves gutter for the longest label present', () => {
  const short = [{ x: FRAME.plotRight + 4, y: 50, text: 'WWC', vendorSlug: 'wwc' }];
  assert.equal(viewboxWidth(short), FRAME.vbW);
  // 'Battlecorals' is the longest real canon label (12 chars).
  const long = [{ x: FRAME.plotRight + 4, y: 50, text: 'Battlecorals', vendorSlug: 'battlecorals' }];
  const w = viewboxWidth(long);
  assert.ok(w > FRAME.vbW);
  assert.ok(w >= FRAME.plotRight + 4 + estimateLabelWidth('Battlecorals'));
});

// ── x ticks ──────────────────────────────────────────────────────────────────
test('xTicks: MMM D uppercase labels, count scales with span', () => {
  const e = [env('2026-03-24', 600), env('2026-06-21', 680)];
  const now = Date.parse('2026-06-21T00:00:00Z');
  const d = computeDomain(e, [], now);
  const ticks = xTicks(d);
  assert.equal(ticks.length, 7);
  assert.match(ticks[0]!.label, /^[A-Z]{3} \d{1,2}$/);
  assert.equal(ticks[ticks.length - 1]!.label, 'JUN 21');
});

// ── thin history ─────────────────────────────────────────────────────────────
test('isThinHistory: single observation = thin; thinObservation returns a REAL price', () => {
  const e = [env('2026-06-19', 420)];
  const tracks = groupByVendor([vp(10, 'pacific_east', '2026-06-19', 420)]);
  assert.equal(isThinHistory(e, tracks), true);
  assert.equal(thinObservation(tracks)?.minPrice, 420); // never null/$0
});

test('isThinHistory: a flat multi-day line is NOT thin', () => {
  const e = [env('2026-06-17', 420), env('2026-06-18', 420), env('2026-06-19', 420)];
  const tracks = groupByVendor([
    vp(10, 'pacific_east', '2026-06-17', 420),
    vp(10, 'pacific_east', '2026-06-19', 420),
  ]);
  assert.equal(isThinHistory(e, tracks), false);
});

test('thinObservation: no per-vendor data → null (page falls back to availability)', () => {
  assert.equal(thinObservation([]), null);
});

test('thinObservation: same-day tie → lowest price, deterministic (not arbitrary)', () => {
  const tracks = groupByVendor([
    vp(10, 'wwc', '2026-06-19', 680),
    vp(20, 'tsa', '2026-06-19', 650), // same day, cheaper
  ]);
  assert.equal(thinObservation(tracks)?.minPrice, 650);
});

test('endLabels: a dense cluster near the axis redistributes, none past axisY', () => {
  // five vendors all bottoming out near the same low price → labels collide and
  // would pile on axisY without the up-pass.
  const tracks = groupByVendor(
    ['a', 'b', 'c', 'd', 'e'].map((s, i) => vp(i + 1, s, '2026-05-20', 100 + i)),
  );
  const now = Date.parse('2026-05-25T00:00:00Z');
  const d = computeDomain([], tracks, now);
  const labels = endLabels(tracks, d, upper);
  for (const l of labels) assert.ok(l.y <= FRAME.axisY);
  const ys = labels.map((l) => l.y).sort((a, b) => a - b);
  for (let i = 1; i < ys.length; i++) {
    assert.ok(ys[i]! - ys[i - 1]! >= 13 - 1e-6, 'min gap preserved after re-stack');
  }
});

// ── nice ticks within ────────────────────────────────────────────────────────
test('niceTicksWithin: round values strictly inside the range', () => {
  const ticks = niceTicksWithin(305, 525, 4);
  assert.ok(ticks.length >= 2);
  for (const t of ticks) assert.ok(t >= 305 && t <= 525);
  const step = ticks[1]! - ticks[0]!;
  for (let i = 1; i < ticks.length; i++) {
    assert.ok(Math.abs(ticks[i]! - ticks[i - 1]! - step) < 1e-6);
  }
});
