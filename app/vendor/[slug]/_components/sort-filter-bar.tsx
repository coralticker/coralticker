// §"Mono uppercase register" — Plex Mono uppercase letterspaced ~0.08em chrome
// above the row stack on paginated inventory surfaces. Brand-canon shape
// locked at /brand-manager session 2026-05-19 (CTK-053 INV-02 pre-first-
// implementation-session gate §Q-1 / §Q-2 / §Q-3); third-axis label flipped
// at /brand-manager session 2026-05-31 (CTK-098 INV-02 gate §Q-1):
//
//   SORT:   NEWEST · PRICE ↑ · PRICE ↓
//   FILTER: LPS · SPS · ZOA · MUSHROOM · CHALICE · CLAM · ANEMONE · SOFTIE
//           INCLUDE OUT OF STOCK
//
// Three stacked axis-rows. Each option is bare Plex Mono uppercase text with
// forest mid-dot separators per <PaginationNav> precedent (register-chrome
// binder, not a sixth forest job). Underline-on-active marks current
// selection; underline-on-hover signals "interactive." Click-active-to-clear
// returns to default state via canonical-chain ?param= omission (same
// discipline as <PaginationNav> page=1 → bare-route at hrefForPage()
// pagination-nav.tsx:31-33).
//
// CTK-098 (2026-05-31): toggle inverted — default state is in-stock-only;
// active state ?include-oos=1 drops the in_stock predicate. Label tracks the
// active semantic (vocabulary-coherent with row-level OUT OF STOCK marker
// per branding-guide.md L228) instead of the prior IN STOCK ONLY framing.
//
// Filter-change href construction omits the ?page= query param entirely —
// changing sort or filter resets pagination to page=1 (which routes bare per
// canonical-chain). CTK-046 upper-clamp Math.min(rawPage, totalPages) at
// app/vendor/[slug]/page.tsx is defense-in-depth for manual URL tampering
// like ?category=sps&page=999.
//
// Single-view co-located per CTK-053 plan §Scope #1 — only /vendor/[slug]
// consumes at v1. Promotes to components/ui/sort-filter-bar.tsx if CTK-009
// Phase 3 cross-surface reuse triggers.

import Link from 'next/link';
import type { ListingCategory, ListingSort } from '@/lib/queries/listings';

interface SortFilterBarProps {
  slug: string;
  sort: ListingSort;
  category: ListingCategory | null;
  includeOOS: boolean;
}

// Category list locked at CTK-053 Session 1 Q-CTK053-3: 8 schema-aligned
// values rendered in display-order per brand-manager session §Q-1 spec
// (LPS top — DB-cardinality lead — then SPS / ZOA / MUSHROOM / CHALICE /
// CLAM / ANEMONE / SOFTIE). Hidden from filter UI: fish / invert / equipment
// / other — vendor-tail noise per plan §Out-of-scope.
const CATEGORY_OPTIONS: { value: ListingCategory; label: string }[] = [
  { value: 'lps', label: 'LPS' },
  { value: 'sps', label: 'SPS' },
  { value: 'zoa', label: 'ZOA' },
  { value: 'mushroom', label: 'MUSHROOM' },
  { value: 'chalice', label: 'CHALICE' },
  { value: 'clam', label: 'CLAM' },
  { value: 'anemone', label: 'ANEMONE' },
  { value: 'softie', label: 'SOFTIE' },
];

// Sort labels per brand-manager session §Q-2 lock — symbol register (↑ / ↓)
// carries direction-as-data; word-pair LOW-TO-HIGH register rejected (extra
// chars, less data-density, register-conflict with PaginationNav's
// no-arrows-on-affordance discipline).
const SORT_OPTIONS: { value: ListingSort; label: string }[] = [
  { value: 'newest', label: 'NEWEST' },
  { value: 'price-asc', label: 'PRICE ↑' },
  { value: 'price-desc', label: 'PRICE ↓' },
];

// Href builder per canonical-chain discipline: default values omit their
// param; page param is dropped on every filter/sort change (filter-change
// resets pagination to page=1 → bare-route).
function buildHref(
  slug: string,
  sort: ListingSort,
  category: ListingCategory | null,
  includeOOS: boolean,
): string {
  const params = new URLSearchParams();
  if (sort !== 'newest') params.set('sort', sort);
  if (category !== null) params.set('category', category);
  if (includeOOS) params.set('include-oos', '1');
  const qs = params.toString();
  return qs ? `/vendor/${slug}?${qs}` : `/vendor/${slug}`;
}

export function SortFilterBar({
  slug,
  sort,
  category,
  includeOOS,
}: SortFilterBarProps) {
  const linkClass =
    'hover:underline focus-visible:underline underline-offset-[3px] decoration-1';
  const activeClass = 'underline underline-offset-[3px] decoration-1';

  // Mid-dot uses non-breaking space BEFORE the dot so it stays glued to the
  // preceding label as an unbreakable unit. Trailing regular space remains a
  // wrap opportunity. CTK-053 Session 3: trailing-dot JSX shape alone wasn't
  // enough — browser greedy line-break at MUSHROOM's preceding-space at 375px
  // still produced a leading-dot line-2 start. nbsp-before-dot forces the
  // break to land at the post-dot space, keeping the dot with the prior label.
  const midDot = (
    <span aria-hidden="true" className="text-forest">
      {' · '}
    </span>
  );

  return (
    <nav
      aria-label="Sort and filter inventory"
      className="pt-6 pb-6 font-mono text-sm uppercase tracking-[0.08em] text-ink flex flex-col gap-y-2"
    >
      <div>
        <span>SORT:</span>{' '}
        {SORT_OPTIONS.map((opt, i) => {
          const isActive = sort === opt.value;
          // Active option clicks clear back to default sort ('newest').
          const targetSort: ListingSort = isActive ? 'newest' : opt.value;
          const href = buildHref(slug, targetSort, category, includeOOS);
          const isLast = i === SORT_OPTIONS.length - 1;
          // Mid-dot TRAILS the preceding option so wrap-breaks keep the dot
          // at end-of-line-N with the previous label, not at start-of-line-N+1
          // before the next label. CTK-053 Session 3 verify: leading-dot on
          // 375px-viewport FILTER row wrap confirmed via Jon DevTools pass.
          return (
            <span key={opt.value}>
              <Link
                href={href}
                className={isActive ? activeClass : linkClass}
                aria-current={isActive ? 'true' : undefined}
              >
                {opt.label}
              </Link>
              {!isLast && midDot}
            </span>
          );
        })}
      </div>

      <div>
        <span>FILTER:</span>{' '}
        {CATEGORY_OPTIONS.map((opt, i) => {
          const isActive = category === opt.value;
          // Active option clicks clear back to no-category (null).
          const targetCategory: ListingCategory | null = isActive
            ? null
            : opt.value;
          const href = buildHref(slug, sort, targetCategory, includeOOS);
          const isLast = i === CATEGORY_OPTIONS.length - 1;
          return (
            <span key={opt.value}>
              <Link
                href={href}
                className={isActive ? activeClass : linkClass}
                aria-current={isActive ? 'true' : undefined}
              >
                {opt.label}
              </Link>
              {!isLast && midDot}
            </span>
          );
        })}
      </div>

      <div>
        <Link
          href={buildHref(slug, sort, category, !includeOOS)}
          className={includeOOS ? activeClass : linkClass}
          aria-current={includeOOS ? 'true' : undefined}
        >
          INCLUDE OUT OF STOCK
        </Link>
      </div>
    </nav>
  );
}
