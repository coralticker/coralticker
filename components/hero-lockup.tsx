// §3.5.2 <HeroLockup>
//
// Homepage hero wrapper around <Wordmark variant="hero">. The horizontal-rule
// + tagline lockup itself renders inside <Wordmark variant="hero"> per §3.1;
// this composition is the layout positioning for the homepage placement.
// No children, no eyebrow, no CTA — content is closed per Decision E + §3.5.2
// composition rules.
//
// CTK-056 S2: mx-auto dropped from section per branding-guide.md L310
// "Left-aligned is the lock." Centered section framed the lockup as
// center-balanced relative to viewport despite the lockup itself being
// left-aligned within the section. Section now left-anchors against the
// page-frame px-6 padding; max-w-3xl bounds the inner reading width.

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
