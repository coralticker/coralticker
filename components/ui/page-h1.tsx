// Page-level H1 typography primitive. Bottom margin is consumer-owned and
// deliberately NOT baked — the mb-{8|6|4} split is surface-rhythm-intentional
// (feed/index H1s breathe at mb-8; detail-page H1s sit tight at mb-4 for
// eyebrow/lineage adjacency; two transitional surfaces at mb-6). Each consumer
// passes its own mb-N via className. A baked default would shift rhythm on 4
// surfaces and double-emit mb- classes against the override.

import type { ReactNode } from 'react';

interface PageH1Props {
  children: ReactNode;
  className?: string;
}

const PAGE_H1_TYPOGRAPHY = 'text-3xl md:text-4xl font-bold';

export function PageH1({ children, className }: PageH1Props) {
  return (
    <h1 className={className ? `${PAGE_H1_TYPOGRAPHY} ${className}` : PAGE_H1_TYPOGRAPHY}>
      {children}
    </h1>
  );
}
