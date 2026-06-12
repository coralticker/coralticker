// Day-bucket transition helpers for <GroupDivider>. The feed surfaces drive
// their dividers through buildBucketedRows(), which composes the two primitives:
//
//   bucketTransition(prev_event_at, curr_event_at)  → boolean
//   bucketLabel(event_at, now)                      → string | null
//
// Threshold gating (12-card minimum, DIVIDER_THRESHOLD) stays view-side —
// buildBucketedRows runs only once a surface is over the threshold.
//
// Label ladder per branding-guide.md §"Group dividers on long feed surfaces":
//   1 day ago     → "YESTERDAY"
//   2-6 days ago  → "X DAYS AGO"  (e.g., "3 DAYS AGO")
//   >= 7 days ago → "MMM D"       (e.g., "APR 24"; uppercase to match register)
//
// All labels render in mono uppercase letterspaced register per
// branding-guide.md §"Mono uppercase register"; this helper emits the literal
// uppercase string. The composition's class wiring applies the typography.

export const DIVIDER_THRESHOLD = 12;

const MONTH_NAMES_UPPER = [
  'JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN',
  'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC',
] as const;

function startOfLocalDay(d: Date): number {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

export function bucketTransition(prevTimestamp: string, currTimestamp: string): boolean {
  const prevDay = startOfLocalDay(new Date(prevTimestamp));
  const currDay = startOfLocalDay(new Date(currTimestamp));
  return prevDay !== currDay;
}

// Total over all (timestamp, now) pairs: dayDiff <= 0 returns null — "no divider
// for this bucket" — instead of throwing. Two callers reach dayDiff <= 0:
//   - same-day (dayDiff = 0): the base no-Today-header rule — a top bucket that
//     IS today gets no leading label;
//   - future-dated (dayDiff < 0): a top row ahead of `now` under midnight
//     Neon-vs-Vercel clock skew — suppressed rather than mislabelled.
// buildBucketedRows relies on this totality, so the helper owns the contract and
// callers just treat null as "skip the divider."
export function bucketLabel(timestamp: string, now: Date): string | null {
  const eventDay = startOfLocalDay(new Date(timestamp));
  const nowDay = startOfLocalDay(now);
  const dayDiff = Math.floor((nowDay - eventDay) / 86_400_000);

  if (dayDiff <= 0) {
    return null;
  }
  if (dayDiff <= 1) {
    return 'YESTERDAY';
  }
  if (dayDiff < 7) {
    return `${dayDiff} DAYS AGO`;
  }
  const d = new Date(timestamp);
  return `${MONTH_NAMES_UPPER[d.getMonth()]} ${d.getDate()}`;
}

// A row paired with the divider label that renders BEFORE it (null = no
// divider). buildBucketedRows annotates a feed in order; the view maps over
// the result, emitting <GroupDivider label={label}/> when label !== null and
// then the surface's own card.
export interface BucketedRow<T> {
  row: T;
  label: string | null;
}

// Centralizes the three hand-rolled divider loops (/new, /deals, /search) into
// one annotate-then-render split. Owns BOTH the inter-row transition AND the
// leading-divider carve-out (branding-guide §"No Today header" leading-divider
// clause): the i === 0 row compares against `now`, so a top bucket that is a
// past local day gets a leading label, a today top bucket gets none (base rule
// re-applies), and a future-dated top row gets none (bucketLabel totality
// suppresses it). Inter-row (i > 0) rows compare prev-vs-curr — with recent-
// first ordering curr is always older, so the label is non-null on every real
// day transition. getTimestamp picks the surface's ordering timestamp
// (eventAt on /new, observedAt on /deals, firstSeenAt on /search).
export function buildBucketedRows<T>(
  rows: T[],
  getTimestamp: (row: T) => string,
  now: Date,
): BucketedRow<T>[] {
  const nowIso = now.toISOString();
  return rows.map((row, i) => {
    const currTs = getTimestamp(row);
    const ref = i === 0 ? nowIso : getTimestamp(rows[i - 1]!);
    const label = bucketTransition(ref, currTs) ? bucketLabel(currTs, now) : null;
    return { row, label };
  });
}
