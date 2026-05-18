// §3.5.2 <HeroLockup>
//
// Homepage hero wrapper around <Wordmark variant="hero">. The horizontal-rule
// + tagline lockup itself renders inside <Wordmark variant="hero"> per §3.1;
// this composition is the layout positioning for the homepage placement.
// No children, no eyebrow, no CTA — content is closed per Decision E + §3.5.2
// composition rules.

import { Wordmark } from '@/components/ui/wordmark';

interface HeroLockupProps {
  tagline?: string;
}

export function HeroLockup({ tagline }: HeroLockupProps) {
  return (
    <section className="px-6 py-16 md:py-24 max-w-3xl mx-auto">
      <Wordmark variant="hero" tagline={tagline} />
    </section>
  );
}
