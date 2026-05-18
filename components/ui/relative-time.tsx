'use client';

// §3.6 <RelativeTime> — the one client-component carve-out from §3 RSC-by-default rule.
//
// Format-ladder logic lives at lib/format/relative-time.ts as the INV-01 channel-parity
// sibling (consumed by formatDataRow() on non-DOM channels at send-time). This component
// is the DOM consumer with live tick via page-level RelativeTimeContext.
//
// SSR/CSR disposition per Q-NEW-A REDISPOSED Option C 2026-05-14:
//   - SSR + initial-CSR render a bones-register pulse-bar matching <DataRowSkeleton> Listed
//     field shape (bg-ink/15 + animate-pulse + h-4 + w-16 + rounded-sm + align-middle).
//     aria-hidden="true" so screen readers don't double-announce post-Suspense — the parent
//     feed's <DataRowSkeleton role="status"> already covered the loading announcement.
//   - useEffect on mount swaps to a <time datetime={...}> element rendering the relative
//     string via formatRelativeTime() consuming RelativeTimeContext's `now`.
//   - Brand-canon (branding-guide.md line 260) requires relative-time across every surface
//     including SSR HTML. Bones-during-hydrate preserves brand-canon by never showing an
//     absolute clock on first-paint; register-continuity with <DataRowSkeleton> means the
//     transition from feed-Suspense → card-with-bones-Listed-field → relative-Listed stays
//     in one visual register.
//   - Animation honors prefers-reduced-motion via app/globals.css → animate-pulse
//     no-op block (CTK-040 Session 1a discipline; same path <DataRowSkeleton> rides).

import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from 'react';
import { formatRelativeTime } from '@/lib/format/relative-time';

const TICK_INTERVAL_MS = 30_000;

const RelativeTimeContext = createContext<Date | null>(null);

export function RelativeTimeProvider({ children }: { children: ReactNode }) {
  const [now, setNow] = useState<Date>(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), TICK_INTERVAL_MS);
    return () => clearInterval(id);
  }, []);
  return (
    <RelativeTimeContext.Provider value={now}>
      {children}
    </RelativeTimeContext.Provider>
  );
}

interface RelativeTimeProps {
  timestamp: string;
}

export function RelativeTime({ timestamp }: RelativeTimeProps) {
  const [hydrated, setHydrated] = useState(false);
  const ctx = useContext(RelativeTimeContext);

  useEffect(() => {
    setHydrated(true);
  }, []);

  if (!hydrated) {
    return (
      <span
        aria-hidden="true"
        className="inline-block h-4 w-16 align-middle bg-ink/15 rounded-sm animate-pulse"
      />
    );
  }

  const now = ctx ?? new Date();
  return <time dateTime={timestamp}>{formatRelativeTime(timestamp, now)}</time>;
}
