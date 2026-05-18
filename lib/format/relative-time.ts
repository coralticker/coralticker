// lib/format/relative-time.ts
//
// Pure relative-time formatter. INV-01 channel-parity sibling per
// site.md §3.6 fold-point E + §3.2 channel-parity:
//   - Web <RelativeTime> (DOM) consumes via components/ui/relative-time.tsx.
//   - formatDataRow() (non-DOM channels — email digest, Discord embed, push body)
//     consumes at send-time with a frozen `now`.
//
// Format ladder per branding-guide.md §"Time format" lines 241-249:
//   < 1h    → "N minute(s) ago"  (singular at N === 1)
//   < 24h   → "N hour(s) ago"    (singular at N === 1)
//   < 7d    → "N day(s) ago"     (singular at N === 1)
//   >= 7d   → "MMM D"            (e.g., "Apr 24")
//
// Locale-independent month formatting (no Intl.DateTimeFormat) so SSR + CSR
// agree byte-for-byte and the build-time output is stable across runners.

const MONTH_NAMES = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
] as const;

export function formatRelativeTime(timestamp: string, now: Date): string {
  const past = new Date(timestamp).getTime();
  const diffMs = now.getTime() - past;
  const diffSec = Math.max(0, Math.floor(diffMs / 1000));

  if (diffSec < 3_600) {
    const minutes = Math.max(1, Math.floor(diffSec / 60));
    return minutes === 1 ? '1 minute ago' : `${minutes} minutes ago`;
  }
  if (diffSec < 86_400) {
    const hours = Math.floor(diffSec / 3_600);
    return hours === 1 ? '1 hour ago' : `${hours} hours ago`;
  }
  if (diffSec < 604_800) {
    const days = Math.floor(diffSec / 86_400);
    return days === 1 ? '1 day ago' : `${days} days ago`;
  }
  const date = new Date(past);
  const month = MONTH_NAMES[date.getMonth()];
  return `${month} ${date.getDate()}`;
}
