// Empty-state is a system-health anomaly: zero recent drops in 24h means
// scrapers are down, not a UX edge case. The strip slot is replaced with the
// downtime-fallback copy.

import type { Metadata } from 'next';
import { HeroLockup } from '@/components/hero-lockup';
import { SignupForm } from '@/components/signup-form';
import { RecentDropsStrip } from '@/app/_components/recent-drops-strip';
import { getRecentDrops } from '@/lib/queries/listings';

export const revalidate = 300;

export const metadata: Metadata = {
  // absolute: opts out of the root title.template — the homepage keeps its
  // full tagline title rather than "CoralTicker — every drop, one feed —
  // CoralTicker".
  title: { absolute: 'CoralTicker — every drop, one feed' },
  description:
    "Drop alerts and price tracking for reef hobbyists. Never miss the piece you've been hunting. Every drop, one feed.",
  alternates: { canonical: '/' },
  // og:title/og:description inherit from title/description; twitter:* falls
  // back to openGraph. Text-only card v1 — no og:image.
  openGraph: { url: '/', siteName: 'CoralTicker', type: 'website', locale: 'en_US' },
  twitter: { card: 'summary' },
};

const DOWNTIME_FALLBACK =
  "No recent drops to show. I'll surface them as scrapers report in.";

export default async function HomePage() {
  const drops = await getRecentDrops();

  return (
    <>
      <HeroLockup />
      {drops.length === 0 ? (
        <section className="px-6 py-8 max-w-3xl mx-auto">
          <p className="text-base text-ink">{DOWNTIME_FALLBACK}</p>
        </section>
      ) : (
        <RecentDropsStrip listings={drops} />
      )}
      <section className="px-6 py-12 max-w-3xl mx-auto">
        <SignupForm source="homepage" />
      </section>
    </>
  );
}
