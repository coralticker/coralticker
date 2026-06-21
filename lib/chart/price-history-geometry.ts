// Pure geometry for the /coral/[slug]/price-history chart (CTK-162 scope b,
// D-3). No React, no data fetching, no Date.now(), no brand canon — every
// function takes its inputs explicitly so the whole module is unit-testable and
// the SVG components stay dumb string-emitters. The page computes `nowMs` once
// and threads it through; vendor labels are injected via a `labelFor` callback
// (brand canon lives in lib/format/vendor-label.ts, not here).
//
// Per-VENDOR model (rewrite 2026-06-21, track-source fork → per-vendor min):
// the chart is a single overlaid plot — one heavy near-black FLOOR line
// (cross-vendor daily-min, get_coral_price_envelope) over one lighter LINE PER
// VENDOR (get_coral_price_by_vendor). Both the floor and each vendor line are
// daily LOCF + honest-gap series BY CONSTRUCTION (a row exists only on days the
// source has an in-stock priced min; absent days are real all-OOS gaps). So
// every line — floor or vendor — breaks the same way: on a day-gap. There is no
// per-point in_stock/null to split on; that was the retired per-listing model.
// Step lines only, no smoothing; forest never appears here.

import type { CoralEnvelopePoint, CoralVendorPricePoint } from '@/lib/queries/coral-price';

const MS_PER_DAY = 86_400_000;

// ── Chart frame (viewBox coordinates; the SVG scales to its container) ───────
export interface Frame {
  vbW: number;
  vbH: number;
  plotLeft: number;
  plotRight: number;
  plotTop: number;
  plotBottom: number;
  axisY: number;
  xLabelY: number;
}

export const FRAME: Frame = {
  vbW: 760,
  vbH: 332,
  plotLeft: 64,
  plotRight: 720,
  plotTop: 24,
  plotBottom: 288,
  axisY: 300,
  xLabelY: 318,
};

export interface Domain {
  t0: number; // earliest data instant (ms epoch)
  t1: number; // now (ms epoch) — the x-axis runs to today even if data ends earlier
  yMin: number;
  yMax: number;
  yTicks: number[];
}

// ── Vendor track = one vendor's daily-min line ───────────────────────────────
export interface VendorTrack {
  vendorId: number;
  vendorSlug: string;
  points: CoralVendorPricePoint[]; // sorted by day ascending
}

// Group the flat (vendor, day) series into one track per vendor, each sorted by
// day. get_coral_price_by_vendor is vendor-major already, but this re-sorts
// defensively so geometry never depends on SQL row order. A vendor appears here
// only if it has ≥1 in-stock priced day (honest gap) — so tracks.length IS the
// rendered vendor count.
export function groupByVendor(points: CoralVendorPricePoint[]): VendorTrack[] {
  const byVendor = new Map<number, VendorTrack>();
  for (const p of points) {
    let track = byVendor.get(p.vendorId);
    if (!track) {
      track = { vendorId: p.vendorId, vendorSlug: p.vendorSlug, points: [] };
      byVendor.set(p.vendorId, track);
    }
    track.points.push(p);
  }
  const tracks = [...byVendor.values()];
  for (const t of tracks) {
    t.points.sort((a, b) => parseDay(a.day) - parseDay(b.day));
  }
  tracks.sort((a, b) => a.vendorId - b.vendorId); // stable render order
  return tracks;
}

function parseDay(day: string): number {
  // `day` is YYYY-MM-DD (TEXT from SQL). Parse at UTC midnight so x-positions
  // are tz-stable and match xTicks' UTC labels. NOTE (CTK-179 (a)): the SQL
  // buckets at session-tz; until neon.ts pins UTC, a near-midnight observation
  // can land one calendar day off here. Deploy-gated, not this module's fix.
  return Date.parse(`${day}T00:00:00Z`);
}

// ── Domain ──────────────────────────────────────────────────────────────────
//
// x-domain = [earliest observed day, now]. Anchoring t1 to now (not the last
// data day) keeps a recently-all-OOS coral honest: its lines end mid-plot and
// the empty right margin reads as "nothing in stock lately." y-domain fits the
// DATA range (small pad), with nice round gridlines INSIDE it — no dead space
// above the highest line (the old niceMax-ceil left a gap).
export function computeDomain(
  envelope: CoralEnvelopePoint[],
  tracks: VendorTrack[],
  nowMs: number,
): Domain {
  const times: number[] = [];
  const prices: number[] = [];
  for (const e of envelope) {
    times.push(parseDay(e.day));
    prices.push(e.minPrice);
  }
  for (const t of tracks) {
    for (const p of t.points) {
      times.push(parseDay(p.day));
      prices.push(p.minPrice);
    }
  }
  const t0 = times.length ? Math.min(...times) : nowMs - 90 * MS_PER_DAY;
  const y = computeYAxis(prices);
  return {
    t0: t0 >= nowMs ? nowMs - MS_PER_DAY : t0, // avoid zero/negative-width domain
    t1: nowMs,
    yMin: y.yMin,
    yMax: y.yMax,
    yTicks: y.yTicks,
  };
}

function computeYAxis(prices: number[]): { yMin: number; yMax: number; yTicks: number[] } {
  if (prices.length === 0) {
    return { yMin: 0, yMax: 100, yTicks: [0, 50, 100] };
  }
  const dataMin = Math.min(...prices);
  const dataMax = Math.max(...prices);
  if (dataMin === dataMax) {
    // Flat series: synthesize a band so the line sits mid-plot, not on an edge.
    const pad = Math.max(Math.abs(dataMin) * 0.1, 1);
    const yMin = dataMin - pad;
    const yMax = dataMax + pad;
    return { yMin, yMax, yTicks: niceTicksWithin(yMin, yMax) };
  }
  // Fit the data range with a small margin (breathing room, not dead space),
  // then place nice round gridlines strictly inside it.
  const pad = (dataMax - dataMin) * 0.06;
  const yMin = dataMin - pad;
  const yMax = dataMax + pad;
  return { yMin, yMax, yTicks: niceTicksWithin(yMin, yMax) };
}

export function xScale(tMs: number, d: Domain, frame: Frame = FRAME): number {
  const plotW = frame.plotRight - frame.plotLeft;
  return frame.plotLeft + ((tMs - d.t0) / (d.t1 - d.t0)) * plotW;
}

export function yScale(price: number, d: Domain, frame: Frame = FRAME): number {
  const plotH = frame.plotBottom - frame.plotTop;
  return frame.plotTop + ((d.yMax - price) / (d.yMax - d.yMin)) * plotH;
}

// ── Daily-series step geometry (shared by the floor + every vendor line) ─────
export interface DailyPoint {
  day: string;
  value: number;
}

export interface SeriesGeometry {
  paths: string[]; // gap-broken step paths (runs of ≥2 days)
  dots: { x: number; y: number }[]; // single-day runs — no line to draw, a point
}

function r(n: number): number {
  return Math.round(n * 100) / 100;
}

// Split a daily series on day-gaps (> 1.5 days between consecutive rows = a real
// all-OOS window), then emit a step-AFTER path per multi-day run and a dot per
// isolated single-day run. Identical break rule for the floor and every vendor
// line — both are honest-gap daily series.
export function dailyStepGeometry(
  points: DailyPoint[],
  d: Domain,
  frame: Frame = FRAME,
): SeriesGeometry {
  if (points.length === 0) return { paths: [], dots: [] };
  const sorted = [...points].sort((a, b) => parseDay(a.day) - parseDay(b.day));
  const runs: DailyPoint[][] = [];
  let run: DailyPoint[] = [sorted[0]!];
  for (let i = 1; i < sorted.length; i++) {
    const gapDays = (parseDay(sorted[i]!.day) - parseDay(sorted[i - 1]!.day)) / MS_PER_DAY;
    if (gapDays > 1.5) {
      runs.push(run);
      run = [];
    }
    run.push(sorted[i]!);
  }
  runs.push(run);

  const paths: string[] = [];
  const dots: { x: number; y: number }[] = [];
  for (const pts of runs) {
    if (pts.length === 1) {
      dots.push({
        x: r(xScale(parseDay(pts[0]!.day), d, frame)),
        y: r(yScale(pts[0]!.value, d, frame)),
      });
      continue;
    }
    let dStr = `M${r(xScale(parseDay(pts[0]!.day), d, frame))},${r(yScale(pts[0]!.value, d, frame))}`;
    for (let i = 1; i < pts.length; i++) {
      const x = r(xScale(parseDay(pts[i]!.day), d, frame));
      dStr += ` L${x},${r(yScale(pts[i - 1]!.value, d, frame))}`; // hold prev
      dStr += ` L${x},${r(yScale(pts[i]!.value, d, frame))}`; // step to current
    }
    paths.push(dStr);
  }
  return { paths, dots };
}

export function floorGeometry(
  envelope: CoralEnvelopePoint[],
  d: Domain,
  frame: Frame = FRAME,
): SeriesGeometry {
  return dailyStepGeometry(
    envelope.map((e) => ({ day: e.day, value: e.minPrice })),
    d,
    frame,
  );
}

export function vendorLineGeometry(
  track: VendorTrack,
  d: Domain,
  frame: Frame = FRAME,
): SeriesGeometry {
  return dailyStepGeometry(
    track.points.map((p) => ({ day: p.day, value: p.minPrice })),
    d,
    frame,
  );
}

// ── End-labels (one per vendor, at its line's last day) ──────────────────────
export interface EndLabel {
  x: number;
  y: number;
  text: string;
  vendorSlug: string; // identity carried through so the consumer can pair adornments (e.g. the N-annotation)
}

const LABEL_MIN_GAP = 13; // px between baselines before de-collision nudges

// One label per vendor track at the END of its line (most recent day — which is
// `now` for a currently-in-stock vendor, or its last in-stock day if OOS).
// `labelFor` injects the brand canon (vendor-label.ts), keeping geometry pure.
// De-collided vertically (greedy push-down), clamped to the plot.
export function endLabels(
  tracks: VendorTrack[],
  d: Domain,
  labelFor: (vendorSlug: string) => string,
  frame: Frame = FRAME,
): EndLabel[] {
  const raw: EndLabel[] = [];
  for (const t of tracks) {
    if (t.points.length === 0) continue;
    const last = t.points[t.points.length - 1]!;
    raw.push({
      x: r(xScale(parseDay(last.day), d, frame) + 4),
      y: r(yScale(last.minPrice, d, frame) + 3.5),
      text: labelFor(t.vendorSlug),
      vendorSlug: t.vendorSlug,
    });
  }
  // Down-pass: push each label below the one above to clear the min gap.
  raw.sort((a, b) => a.y - b.y);
  for (let i = 1; i < raw.length; i++) {
    if (raw[i]!.y < raw[i - 1]!.y + LABEL_MIN_GAP) {
      raw[i]!.y = raw[i - 1]!.y + LABEL_MIN_GAP;
    }
  }
  // Up-pass: a dense cluster can push the bottom labels past the axis; a naive
  // clamp would re-stack them all on axisY. Clamp the bottom one, then walk
  // upward keeping the min gap so the overflow redistributes into free space
  // above instead of collapsing into a pile.
  for (let i = raw.length - 1; i >= 0; i--) {
    if (raw[i]!.y > frame.axisY) raw[i]!.y = frame.axisY;
    if (i < raw.length - 1 && raw[i]!.y > raw[i + 1]!.y - LABEL_MIN_GAP) {
      raw[i]!.y = raw[i + 1]!.y - LABEL_MIN_GAP;
    }
  }
  return raw;
}

// Plex Mono advance at the end-label font-size (10.5px) ≈ 0.6em → ~6.3px/char.
const LABEL_CHAR_PX = 6.3;

export function estimateLabelWidth(text: string): number {
  return text.length * LABEL_CHAR_PX;
}

// Right-margin gutter rule (/brand-manager canon): reserve room for the LONGEST
// end-label ACTUALLY PRESENT so a full-name fallback (Battlecorals, Cornbred
// Corals) never overflows. The plot geometry is untouched; only the viewBox
// WIDTH grows, and since the SVG scales to its container the chart just shrinks
// a hair. Never below the frame's own vbW.
export function viewboxWidth(labels: EndLabel[], frame: Frame = FRAME): number {
  let maxRight = frame.vbW;
  for (const l of labels) {
    maxRight = Math.max(maxRight, l.x + estimateLabelWidth(l.text) + 6);
  }
  return Math.round(maxRight);
}

// ── Axis ticks ───────────────────────────────────────────────────────────────
export interface XTick {
  x: number;
  label: string;
}

const MONTHS = [
  'JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN',
  'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC',
];

function formatTickLabel(tMs: number, spanDays: number): string {
  const dt = new Date(tMs);
  const mon = MONTHS[dt.getUTCMonth()]!;
  if (spanDays >= 365) {
    return `${mon} '${String(dt.getUTCFullYear()).slice(2)}`;
  }
  return `${mon} ${dt.getUTCDate()}`;
}

export function xTicks(d: Domain, frame: Frame = FRAME): XTick[] {
  const spanDays = (d.t1 - d.t0) / MS_PER_DAY;
  const count = spanDays <= 14 ? 4 : spanDays <= 45 ? 5 : 7;
  const ticks: XTick[] = [];
  for (let i = 0; i < count; i++) {
    const tMs = d.t0 + ((d.t1 - d.t0) * i) / (count - 1);
    ticks.push({ x: r(xScale(tMs, d, frame)), label: formatTickLabel(tMs, spanDays) });
  }
  return ticks;
}

// ── Thin-history detection ───────────────────────────────────────────────────
//
// "Thin" = not enough to draw a meaningful line: the floor has ≤1 day AND no
// single vendor carries ≥2 days. A flat multi-day line is NOT thin (it draws an
// honest flat line).
export function isThinHistory(envelope: CoralEnvelopePoint[], tracks: VendorTrack[]): boolean {
  if (envelope.length > 1) return false;
  return !tracks.some((t) => t.points.length >= 2);
}

// The single observation to surface in the thin-history state: the most recent
// per-vendor point (a REAL in-stock min — get_coral_price_by_vendor never emits
// null/$0). Returns null when there is no per-vendor priced data at all; the
// page then sources from availability (which CAN be null-price → "price on
// request", never a fabricated $0).
export function thinObservation(tracks: VendorTrack[]): CoralVendorPricePoint | null {
  const all = tracks.flatMap((t) => t.points);
  if (!all.length) return null;
  // Most recent day; on a same-day tie pick the lowest price — deterministic
  // (a bare >= would return whichever vendor happened to come last).
  return all.reduce((a, b) => {
    const da = parseDay(a.day);
    const db = parseDay(b.day);
    if (db > da) return b;
    if (db < da) return a;
    return b.minPrice < a.minPrice ? b : a;
  });
}

// ── Nice ticks (Heckbert) ────────────────────────────────────────────────────
function niceNum(range: number, round: boolean): number {
  const exp = Math.floor(Math.log10(range));
  const frac = range / Math.pow(10, exp);
  let nice: number;
  if (round) {
    nice = frac < 1.5 ? 1 : frac < 3 ? 2 : frac < 7 ? 5 : 10;
  } else {
    nice = frac <= 1 ? 1 : frac <= 2 ? 2 : frac <= 5 ? 5 : 10;
  }
  return nice * Math.pow(10, exp);
}

// Nice round tick values STRICTLY INSIDE [lo, hi] — used for the data-fitted
// y-axis so gridlines sit within the rendered range, never above the top line.
export function niceTicksWithin(lo: number, hi: number, count = 4): number[] {
  const span = hi - lo;
  if (span <= 0) return [Math.round(lo)];
  const step = niceNum(span / count, true);
  const first = Math.ceil(lo / step) * step;
  const ticks: number[] = [];
  for (let v = first; v <= hi + 1e-9; v += step) {
    ticks.push(Math.round(v * 100) / 100);
  }
  // Degenerate guard: a very tight range can admit no in-range nice multiple —
  // fall back to the midpoint so the axis renders a single reference line.
  return ticks.length ? ticks : [Math.round(((lo + hi) / 2) * 100) / 100];
}
