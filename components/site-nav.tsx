// §3.5.9 <SiteNav> — sitewide layout chrome
//
// Top-bar nav composition: left-aligned <Wordmark variant="nav"> as the
// home click target + middle-cluster IA links (NEW · DEALS · CORALS ·
// VENDORS · ABOUT) bound by forest mid-dot separators + right-aligned
// SIGNUP CTA. Wired into app/layout.tsx above <main>; consumed by every
// Phase 2 view.
//
// CTK-048 INV-02 locks per
// .claude/plans/tickets/CTK-048/brand-manager-session-2026-05-20.md:
//   Q-1: middle-cluster order NEW · DEALS · VENDORS · ABOUT (freshness-first)
//        — amended CTK-057 (/brand-manager canon-amendment 2026-06-04):
//        CORALS added at index 2 → NEW · DEALS · CORALS · VENDORS · ABOUT.
//        Freshness pair leads per the Q-1 rationale; browse-index pair
//        adjacent, content-noun before source-noun; ABOUT terminal.
//   Q-2: SIGNUP bare-text mono-uppercase, underline-on-hover, no chip/fill
//   Q-3: active-route `underline underline-offset-[3px] decoration-1`;
//        wordmark exempt (brand-anchor, not IA peer — hover-underline only)
//   Q-4: text-lg wordmark over text-xs chrome (~1.5×); scaling wrapped at
//        this consumer site to preserve Footer text-sm cascade
//   Q-5: forest mid-dot binder INTERNAL to middle-cluster (canon-extension
//        per <PaginationNav> precedent)
//   Q-6: bare-gap cluster separation (no separator chrome between Wordmark
//        / middle-cluster / right-CTA)
//
// Client-component carve-out per site.md §0.2 #2: active-route detection
// via usePathname() requires client JS — Q-3 cannot render correctly from
// a pure RSC at the layout level. Same narrow-leaf carve-out pattern as
// <SignupForm> (§3.5.8). No other client behavior at v1; search-bar
// typeahead deferred to CTK-058.
//
// Mobile pattern: flex-wrap on the nav row + flex-wrap inside the middle
// cluster <ul>, with each link + trailing forest mid-dot pair wrapped in
// a `whitespace-nowrap` <li> so wrap points only fall between pairs, not
// inside a pair (prevents orphan mid-dots). No hamburger drawer, no
// stacked-nav layout switch (per CTK-053 <SortFilterBar> precedent).

'use client';

import { Fragment } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Wordmark } from '@/components/ui/wordmark';

interface NavLink {
  href: string;
  label: string;
}

const NAV_LINKS: NavLink[] = [
  { href: '/new', label: 'NEW' },
  { href: '/deals', label: 'DEALS' },
  { href: '/corals', label: 'CORALS' },
  { href: '/vendors', label: 'VENDORS' },
  { href: '/about', label: 'ABOUT' },
];

const linkClass =
  'hover:underline focus-visible:underline underline-offset-[3px] decoration-1';
const activeLinkClass = 'underline underline-offset-[3px] decoration-1';

export function SiteNav() {
  const pathname = usePathname();

  return (
    <nav
      aria-label="Site navigation"
      className="px-6 py-4 flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2"
    >
      <Link href="/" className={`text-lg ${linkClass}`}>
        <Wordmark variant="nav" />
      </Link>

      <ul className="list-none p-0 m-0 font-mono text-xs uppercase tracking-[0.08em] text-ink">
        {NAV_LINKS.map((link, i) => {
          const isActive = pathname === link.href;
          const isLast = i === NAV_LINKS.length - 1;
          return (
            <Fragment key={link.href}>
              <li className="inline whitespace-nowrap">
                <Link
                  href={link.href}
                  aria-current={isActive ? 'page' : undefined}
                  className={isActive ? activeLinkClass : linkClass}
                >
                  {link.label}
                </Link>
                {!isLast && (
                  <span aria-hidden="true" className="text-forest">
                    {' · '}
                  </span>
                )}
              </li>
              {!isLast && ' '}
            </Fragment>
          );
        })}
      </ul>

      <Link
        href="/signup"
        className={`font-mono text-xs uppercase tracking-[0.08em] text-ink ${
          pathname === '/signup' ? activeLinkClass : linkClass
        }`}
      >
        SIGNUP
      </Link>
    </nav>
  );
}
