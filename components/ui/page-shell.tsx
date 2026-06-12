// Shared outer page wrapper — the single source for the page-shell chrome
// recipe consumed by every standalone page surface. app/layout.tsx already
// owns the document's single <main>, so a page must NOT render its own <main>
// (two <main> landmarks = ambiguous primary landmark + WAI-ARIA violation).
// PageShell renders a sibling landmark (<article>) or region (<section>)
// inside the layout's <main> via the `as` prop — <article> for single-entity
// primary content (/coral/[slug], /vendor/[slug] detail), <section> everywhere
// else.
//
// `className` is an escape-hatch for surface-specific overrides; no v1 consumer
// passes one (all share the canonical chrome exactly).

import type { ReactNode } from 'react';

interface PageShellProps {
  as: 'section' | 'article';
  className?: string;
  children: ReactNode;
}

const PAGE_SHELL_CHROME = 'px-6 py-12 max-w-3xl mx-auto';

export function PageShell({ as: As, className, children }: PageShellProps) {
  return (
    <As className={className ? `${PAGE_SHELL_CHROME} ${className}` : PAGE_SHELL_CHROME}>
      {children}
    </As>
  );
}
