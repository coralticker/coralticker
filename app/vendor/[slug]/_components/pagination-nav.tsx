// §"Mono uppercase register" — Plex Mono uppercase letterspaced ~0.08em chrome
// terminating the row stack on paginated inventory surfaces. Brand-canon shape
// locked at /brand-manager session 2026-05-18 §Q-5 (CTK-040 close-sweep):
//
//   PREV · PAGE 2 OF 7 · NEXT
//
// Forest mid-dot separators bind the three segments as a single chrome unit
// (eyebrow precedent — branding-guide.md §"Mono uppercase register" line 206);
// bare PREV / NEXT text with underline-on-hover (no arrows; no color shift on
// hover per §"Color system" line 175 anti-dilution rule); disabled state at
// boundary pages = opacity 0.4 + no underline (no color shift); vertical
// rhythm pt-7 (28px above, separates from final row) + pb-4 (16px below,
// signals list-bottom) per §"Group dividers" line 287 precedent.
//
// Single-view co-located per CTK-046 plan §Decision D inclusion bar — only
// /vendor/[slug] consumes at v1. Promotes to components/ui/pagination-nav.tsx
// when a second view adopts pagination (live trigger: CTK-015 first-ship
// Lighthouse audit on /new or /deals reopening their LIMIT 100 caps).

import Link from 'next/link';

interface PaginationNavProps {
  currentPage: number;
  totalPages: number;
  slug: string;
}

// Page 1 routes to bare URL per site.md §6 SEO discipline (canonical = bare
// route, no ?page query) — keeps prev/next href shape consistent with the
// canonical chain.
function hrefForPage(slug: string, page: number): string {
  return page === 1 ? `/vendor/${slug}` : `/vendor/${slug}?page=${page}`;
}

export function PaginationNav({ currentPage, totalPages, slug }: PaginationNavProps) {
  const prevDisabled = currentPage <= 1;
  const nextDisabled = currentPage >= totalPages;

  const linkClass =
    'hover:underline focus-visible:underline underline-offset-[3px] decoration-1';
  const disabledClass = 'opacity-40';

  const prev = prevDisabled ? (
    <span className={disabledClass}>PREV</span>
  ) : (
    <Link href={hrefForPage(slug, currentPage - 1)} className={linkClass}>
      PREV
    </Link>
  );

  const next = nextDisabled ? (
    <span className={disabledClass}>NEXT</span>
  ) : (
    <Link href={hrefForPage(slug, currentPage + 1)} className={linkClass}>
      NEXT
    </Link>
  );

  return (
    <nav
      aria-label="Pagination"
      className="pt-7 pb-4 font-mono text-xs uppercase tracking-[0.08em] text-ink"
    >
      {prev}
      <span aria-hidden="true" className="text-forest">{' · '}</span>
      <span>
        PAGE {currentPage} OF {totalPages}
      </span>
      <span aria-hidden="true" className="text-forest">{' · '}</span>
      {next}
    </nav>
  );
}
