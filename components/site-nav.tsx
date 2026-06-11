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
// Server Component shell (CTK-064): active-route detection moved to the
// <ActiveLink> client leaf. usePathname() requires client JS — Q-3 cannot
// render from a pure RSC — but only the link active-state needs it, so the
// whole nav no longer ships 'use client'. Wordmark, mid-dot separators,
// and <SearchBar> are pure markup; only <ActiveLink> instances are client.
// Same narrow-leaf carve-out pattern as <SignupForm> (§3.5.8), now scoped
// to the leaf instead of the shell. No other client behavior at v1;
// typeahead stays CTK-058 v2.
//
// CTK-058 v1: <SearchBar> mounts bare-gap-separated between the link run
// and SIGNUP per the INV-02 round-2 variant A lock (branding-guide L286) —
// a control is the third bare-gap non-peer species; never inside the
// mid-dot run (its every-item-navigates grammar binds IA peers only). The
// bar is a hook-free GET form — RSC-safe.
//
// Mobile pattern: flex-wrap on the nav row + flex-wrap inside the middle
// cluster <ul>, with each link + trailing forest mid-dot pair wrapped in
// a `whitespace-nowrap` <li> so wrap points only fall between pairs, not
// inside a pair (prevents orphan mid-dots). No hamburger drawer, no
// stacked-nav layout switch (per CTK-053 <SortFilterBar> precedent).

import { Fragment } from 'react';
import Link from 'next/link';
import { ActiveLink, linkClass } from '@/components/active-link';
import { SearchBar } from '@/components/ui/search-bar';
import { Wordmark } from '@/components/ui/wordmark';

interface NavLink {
  href: string;
  label: string;
  matchPrefixes?: string[];
}

// Active-state policy (Jon-confirmed CTK-064: detail pages light their
// index). matchPrefixes is the distinct detail stem, not an href-prefix —
// VENDORS /vendors lights on /vendor/[slug]; CORALS /corals on /coral/[slug].
// Stems carry a trailing slash so they only match at the sub-route boundary:
// index pages light via href-exact, never via a bare-prefix collision with a
// future sibling route (e.g. /vendor-guide, /coral-care).
const NAV_LINKS: NavLink[] = [
  { href: '/new', label: 'NEW' },
  { href: '/deals', label: 'DEALS' },
  { href: '/corals', label: 'CORALS', matchPrefixes: ['/coral/'] },
  { href: '/vendors', label: 'VENDORS', matchPrefixes: ['/vendor/'] },
  { href: '/about', label: 'ABOUT' },
];

// SIGNUP supplies its own font run (the middle cluster inherits font-mono
// etc. from the <ul>); ActiveLink prepends it to the link/active class.
const signupClass = 'font-mono text-xs uppercase tracking-[0.08em] text-ink';

export function SiteNav() {
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
          const isLast = i === NAV_LINKS.length - 1;
          return (
            <Fragment key={link.href}>
              <li className="inline whitespace-nowrap">
                <ActiveLink
                  href={link.href}
                  label={link.label}
                  matchPrefixes={link.matchPrefixes}
                />
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

      <SearchBar />

      <ActiveLink
        href="/signup"
        label="SIGNUP"
        matchPrefixes={['/signup/']}
        className={signupClass}
      />
    </nav>
  );
}
