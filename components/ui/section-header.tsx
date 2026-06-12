// Below-H1 section-header primitive. The mb-2 IS baked here — the under-rule-to-
// content gap is identical across all 4 sites, so the margin is canon-neutral
// and lives in the primitive. border-line is the single hairline tone.

import type { ReactNode } from 'react';

interface SectionHeaderProps {
  children: ReactNode;
  className?: string;
}

const SECTION_HEADER_CHROME = 'text-sm font-bold pb-2 mb-2 border-b border-line';

export function SectionHeader({ children, className }: SectionHeaderProps) {
  return (
    <h2 className={className ? `${SECTION_HEADER_CHROME} ${className}` : SECTION_HEADER_CHROME}>
      {children}
    </h2>
  );
}
