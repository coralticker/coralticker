// §"Mono uppercase register" — Plex Mono uppercase letterspaced ~0.08em chrome
// above the row stack on paginated inventory surfaces:
//
//   SORT:   NEWEST · PRICE ↑ · PRICE ↓
//   FILTER: LPS · SPS · ZOA · MUSHROOM · CHALICE · CLAM · ANEMONE · SOFTIE
//           INCLUDE OUT OF STOCK
//
// Stacked axis-rows. Each option is bare Plex Mono uppercase text with forest
// mid-dot separators. Underline-on-active marks current selection;
// underline-on-hover signals "interactive." Click-active-to-clear returns to
// default state via canonical-chain ?param= omission (same discipline as
// <PaginationNav> page=1 → bare-route).
//
// OOS toggle is inverted — default state is in-stock-only; active state
// ?include-oos=1 drops the in_stock predicate. Label tracks the active semantic
// (vocabulary-coherent with the row-level OUT OF STOCK marker) instead of an
// IN STOCK ONLY framing.
//
// Filter-change href construction omits the ?page= query param entirely —
// changing sort or filter resets pagination to page=1 (which routes bare per
// canonical-chain). The upper-clamp Math.min(rawPage, totalPages) at
// app/vendor/[slug]/page.tsx is defense-in-depth for manual URL tampering
// like ?category=sps&page=999.
//
// Axis-subset API: /vendor/[slug] renders all three axes (includeOOS: boolean);
// /new + /deals render SORT + FILTER only (includeOOS omitted — feeds filter
// in_stock = true at the query layer; no OOS axis on feed surfaces).
// /coral/[slug]'s single-axis toggle stays a local variant — not a consumer of
// this component.

import Link from 'next/link';
import type { ListingCategory, ListingSort } from '@/lib/queries/listings';
import { CATEGORY_LABELS, SORT_LABELS } from '@/lib/queries/listing-params';

interface SortFilterBarProps {
  // Route the axis hrefs resolve against — '/vendor/{slug}', '/new', '/deals'.
  basePath: string;
  sort: ListingSort;
  category: ListingCategory | null;
  // undefined = OOS axis not rendered (feed surfaces); boolean = axis
  // rendered with that toggle state (inventory-recon surfaces).
  includeOOS?: boolean;
  // Feeds pass "Sort and filter listings"; the default keeps the inventory
  // wording on /vendor/[slug].
  ariaLabel?: string;
}

// Option rows derive from the label records in lib/queries/listing-params.ts
// — record insertion order carries the brand-locked display order. Add a chip
// by editing the record, not this file.
const SORT_OPTIONS = (
  Object.entries(SORT_LABELS) as [ListingSort, string][]
).map(([value, label]) => ({ value, label }));

const CATEGORY_OPTIONS = (
  Object.entries(CATEGORY_LABELS) as [ListingCategory, string][]
).map(([value, label]) => ({ value, label }));

// Href builder per canonical-chain discipline: default values omit their
// param; page param is dropped on every filter/sort change (filter-change
// resets pagination to page=1 → bare-route). undefined includeOOS (feed
// surfaces) never emits the param.
function buildHref(
  basePath: string,
  sort: ListingSort,
  category: ListingCategory | null,
  includeOOS: boolean | undefined,
): string {
  const params = new URLSearchParams();
  if (sort !== 'newest') params.set('sort', sort);
  if (category !== null) params.set('category', category);
  if (includeOOS) params.set('include-oos', '1');
  const qs = params.toString();
  return qs ? `${basePath}?${qs}` : basePath;
}

export function SortFilterBar({
  basePath,
  sort,
  category,
  includeOOS,
  ariaLabel = 'Sort and filter inventory',
}: SortFilterBarProps) {
  const linkClass =
    'hover:underline focus-visible:underline underline-offset-[3px] decoration-1';
  const activeClass = 'underline underline-offset-[3px] decoration-1';

  // Mid-dot uses non-breaking space BEFORE the dot so it stays glued to the
  // preceding label as an unbreakable unit. Trailing regular space remains a
  // wrap opportunity. Trailing-dot JSX shape alone wasn't enough — a browser's
  // greedy line-break at a preceding-space at 375px still produced a leading-dot
  // line-2 start; nbsp-before-dot forces the break to land at the post-dot
  // space, keeping the dot with the prior label.
  // NBSP + mid-dot written as \u00A0\u00B7 escapes — the literal char is
  // silently flattened to a regular space, so the escape stays grep- and
  // review-visible.
  const midDot = (
    <span aria-hidden="true" className="text-forest">
      {'\u00A0\u00B7 '}
    </span>
  );

  return (
    <nav
      aria-label={ariaLabel}
      className="pt-6 pb-6 font-mono text-sm uppercase tracking-[0.08em] text-ink flex flex-col gap-y-2"
    >
      <div>
        <span>SORT:</span>{' '}
        {SORT_OPTIONS.map((opt, i) => {
          const isActive = sort === opt.value;
          // Active option clicks clear back to default sort ('newest').
          const targetSort: ListingSort = isActive ? 'newest' : opt.value;
          const href = buildHref(basePath, targetSort, category, includeOOS);
          const isLast = i === SORT_OPTIONS.length - 1;
          // Mid-dot TRAILS the preceding option so wrap-breaks keep the dot
          // at end-of-line-N with the previous label, not at start-of-line-N+1
          // before the next label.
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
          const href = buildHref(basePath, sort, targetCategory, includeOOS);
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

      {includeOOS !== undefined && (
        <div>
          <Link
            href={buildHref(basePath, sort, category, !includeOOS)}
            className={includeOOS ? activeClass : linkClass}
            aria-current={includeOOS ? 'true' : undefined}
          >
            INCLUDE OUT OF STOCK
          </Link>
        </div>
      )}
    </nav>
  );
}
