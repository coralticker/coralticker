// §"Mono uppercase register" — Plex Mono uppercase letterspaced ~0.08em chrome
// terminating the row stack on paginated inventory surfaces:
//
//   PREV · PAGE 2 OF 7 · NEXT
//
// Forest mid-dot separators bind the three segments as a single chrome unit;
// bare PREV / NEXT text with underline-on-hover (no arrows; no color shift on
// hover per the §"Color system" anti-dilution rule); disabled state at
// boundary pages = opacity 0.4 + no underline (no color shift).

import Link from 'next/link';
import type { ListingCategory, ListingSort } from '@/lib/queries/listings';

interface PaginationNavProps {
  currentPage: number;
  totalPages: number;
  slug: string;
  // Filter/sort state preserved across pagination — clicking NEXT on
  // /vendor/wwc?category=sps routes to /vendor/wwc?category=sps&page=2, not
  // /vendor/wwc?page=2. Defaults match the no-filter/no-sort case.
  sort?: ListingSort;
  category?: ListingCategory | null;
  includeOOS?: boolean;
}

// Page 1 routes to bare URL (canonical = bare route, no ?page query) — keeps
// prev/next href shape consistent with the canonical chain. Sort + category +
// in-stock params preserved on every prev/next href so pagination stays inside
// the filtered subset.
function hrefForPage(
  slug: string,
  page: number,
  sort: ListingSort,
  category: ListingCategory | null,
  includeOOS: boolean,
): string {
  const params = new URLSearchParams();
  if (sort !== 'newest') params.set('sort', sort);
  if (category !== null) params.set('category', category);
  if (includeOOS) params.set('include-oos', '1');
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
  includeOOS = false,
}: PaginationNavProps) {
  const prevDisabled = currentPage <= 1;
  const nextDisabled = currentPage >= totalPages;

  const linkClass =
    'hover:underline focus-visible:underline underline-offset-[3px] decoration-1';
  const disabledClass = 'opacity-40';

  const prev = prevDisabled ? (
    <span aria-disabled="true" className={disabledClass}>PREV</span>
  ) : (
    <Link
      href={hrefForPage(slug, currentPage - 1, sort, category, includeOOS)}
      className={linkClass}
    >
      PREV
    </Link>
  );

  const next = nextDisabled ? (
    <span aria-disabled="true" className={disabledClass}>NEXT</span>
  ) : (
    <Link
      href={hrefForPage(slug, currentPage + 1, sort, category, includeOOS)}
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
