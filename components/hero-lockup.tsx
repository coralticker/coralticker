// mx-auto is deliberately absent per branding-guide §"Left-aligned is the
// lock": a centered section frames the lockup as center-balanced relative to
// viewport despite the lockup being left-aligned within the section. The
// section left-anchors against the page-frame px-6 padding; max-w-3xl bounds
// the inner reading width.

import { Wordmark } from '@/components/ui/wordmark';

interface HeroLockupProps {
  tagline?: string;
}

export function HeroLockup({ tagline }: HeroLockupProps) {
  return (
    <section className="px-6 py-16 md:py-24 max-w-3xl">
      <Wordmark variant="hero" tagline={tagline} />
    </section>
  );
}
