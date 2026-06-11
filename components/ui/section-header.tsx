// Below-H1 section-header primitive — extracted at CTK-084 (F-S7-12).
// The 4 content-surface <h2> section headers repeated the same typography +
// under-rule chrome; this primitive holds it structurally.
//
// Typography + border canon ratified /brand-manager 2026-06-11 Element 2
// (served-neutral): text-sm font-bold pb-2 mb-2 border-b border-line. The mb-2
// IS baked here — the served under-rule-to-content gap is identical across all
// 4 sites (Element 3), so the margin is canon-neutral and lives in the
// primitive. border-line is the single hairline tone (CTK-129 served-neutral
// re-spec; the plan's border-ink/20-vs-/30 risk is moot — both resolved to it).
//
// Copy passes through verbatim as children — copy-agnostic, no register prop
// (incl. the state-dynamic {sectionHeader} at /coral/[slug]). The sentence-case
// `.`-terminated content register lives at the consumer call site.

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
