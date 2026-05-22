// lib/format/group-bucket.ts
//
// Day-bucket transition helpers for <GroupDivider> (§3.5.7). The view loop in
// /new (and any feed surface that crosses day boundaries with 12+ cards per
// branding-guide.md §"Group dividers on long feed surfaces" line 257) calls:
//
//   bucketTransition(prev_event_at, curr_event_at)  → boolean
//   bucketLabel(event_at, now)                      → string
//
// The composition takes the formatted label and renders. Threshold gating
// (12-card minimum) stays view-side per site.md §3.5.7 composition rules.
//
// Label ladder per branding-guide.md §"Group dividers" line 260:
//   1 day ago     → "YESTERDAY"
//   2-6 days ago  → "X DAYS AGO"  (e.g., "3 DAYS AGO")
//   >= 7 days ago → "MMM D"       (e.g., "APR 24"; uppercase to match register)
//
// All labels render in mono uppercase letterspaced register per
// branding-guide.md §"Mono uppercase register"; this helper emits the literal
// uppercase string. The composition's class wiring applies the typography.

// Minimum feed size at which day-bucket dividers fire per branding-guide.md
// §"Group dividers on long feed surfaces" line 257. Threshold is shared by /new
// + /deals view loops; gating + bucketTransition pairing lives view-side, but
// the literal lives here alongside the helpers it pairs with.
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

export function bucketLabel(timestamp: string, now: Date): string {
  const eventDay = startOfLocalDay(new Date(timestamp));
  const nowDay = startOfLocalDay(now);
  const dayDiff = Math.floor((nowDay - eventDay) / 86_400_000);

  // Caller contract: dayDiff must be positive. Same-day passthrough (dayDiff=0)
  // is a caller bug — bucketTransition() suppresses same-day pairs, so this
  // helper should never receive one. Without the throw, dayDiff=0 silently
  // returned "YESTERDAY" per the `<= 1` ladder.
  if (dayDiff <= 0) {
    throw new Error('bucketLabel: dayDiff must be positive (same-day passthrough is a caller bug)');
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
