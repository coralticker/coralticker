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
import type { ListingCategory, ListingSort } from '@/lib/queries/listings';

interface PaginationNavProps {
  currentPage: number;
  totalPages: number;
  slug: string;
  // CTK-053: filter/sort state preserved across pagination — clicking NEXT
  // on /vendor/wwc?category=sps routes to /vendor/wwc?category=sps&page=2,
  // not /vendor/wwc?page=2. Defaults match the no-filter/no-sort case so
  // pre-CTK-053 callers (none currently — single-view co-located) stay
  // untouched.
  sort?: ListingSort;
  category?: ListingCategory | null;
  inStock?: boolean;
}

// Page 1 routes to bare URL per site.md §6 SEO discipline (canonical = bare
// route, no ?page query) — keeps prev/next href shape consistent with the
// canonical chain. CTK-053: sort + category + in-stock params preserved on
// every prev/next href so pagination stays inside the filtered subset.
function hrefForPage(
  slug: string,
  page: number,
  sort: ListingSort,
  category: ListingCategory | null,
  inStock: boolean,
): string {
  const params = new URLSearchParams();
  if (sort !== 'newest') params.set('sort', sort);
  if (category !== null) params.set('category', category);
  if (inStock) params.set('in-stock', '1');
  if (page !== 1) params.set('page', String(page));
  const qs = params.toString();
  return qs ? `/vendor/${slug}?${qs}` : `/vendor/${slug}`;
}

export function PaginationNav({
  currentPage,
  totalPages,
  slug,
  sort = 'newest',
  category = null,
  inStock = false,
}: PaginationNavProps) {
  const prevDisabled = currentPage <= 1;
  const nextDisabled = currentPage >= totalPages;

  const linkClass =
    'hover:underline focus-visible:underline underline-offset-[3px] decoration-1';
  const disabledClass = 'opacity-40';

  const prev = prevDisabled ? (
    <span className={disabledClass}>PREV</span>
  ) : (
    <Link
      href={hrefForPage(slug, currentPage - 1, sort, category, inStock)}
      className={linkClass}
    >
      PREV
    </Link>
  );

  const next = nextDisabled ? (
    <span className={disabledClass}>NEXT</span>
  ) : (
    <Link
      href={hrefForPage(slug, currentPage + 1, sort, category, inStock)}
      className={linkClass}
    >
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
