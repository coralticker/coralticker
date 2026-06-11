// Page-level H1 typography primitive — extracted at CTK-084 (F-S7-13).
// The 11 prose-register page H1s repeated the same typography string; this
// primitive holds the one canon shape.
//
// Typography canon ratified /brand-manager 2026-06-11 Element 1 (served-neutral
// — string already canon via CTK-077 Element 2, the NotFoundShell H1): the
// className IS the canon, nothing more. Bottom margin is consumer-owned and
// deliberately NOT baked — the mb-{8|6|4} split is surface-rhythm-intentional
// (feed/index H1s breathe at mb-8; detail-page H1s sit tight at mb-4 for
// eyebrow/lineage adjacency; two transitional surfaces at mb-6). Each consumer
// passes its own mb-N via className. A baked default would shift rhythm on 4
// surfaces and double-emit mb- classes against the override.
//
// Copy passes through verbatim as children — copy-agnostic, no register prop;
// the prose-register `.`-terminated casing lives at the consumer call site.

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
