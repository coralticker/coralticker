// Server Component shell: active-route detection moved to the <ActiveLink>
// client leaf. usePathname() requires client JS, but only the link
// active-state needs it, so the whole nav no longer ships 'use client'.
// Wordmark, mid-dot separators, and <SearchBar> are pure markup; only
// <ActiveLink> instances are client.
//
// <SearchBar> mounts bare-gap-separated between the link run and SIGNUP — a
// control is a third bare-gap non-peer species; never inside the mid-dot run
// (its every-item-navigates grammar binds IA peers only). The bar is a
// hook-free GET form — RSC-safe.
//
// Mobile pattern: flex-wrap on the nav row + flex-wrap inside the middle
// cluster <ul>, with each link + trailing forest mid-dot pair wrapped in
// a `whitespace-nowrap` <li> so wrap points only fall between pairs, not
// inside a pair (prevents orphan mid-dots).

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

// Active-state policy: detail pages light their index. matchPrefixes is the
// distinct detail stem, not an href-prefix — VENDORS /vendors lights on
// /vendor/[slug]; CORALS /corals on /coral/[slug]. Stems carry a trailing
// slash so they only match at the sub-route boundary: index pages light via
// href-exact, never via a bare-prefix collision with a future sibling route
// (e.g. /vendor-guide, /coral-care).
const NAV_LINKS: NavLink[] = [
  { href: '/new', label: 'NEW' },
  { href: '/deals', label: 'DEALS' },
  { href: '/corals', label: 'CORALS', matchPrefixes: ['/coral/'] },
  { href: '/vendors', label: 'VENDORS', matchPrefixes: ['/vendor/'] },
  { href: '/guides', label: 'GUIDES', matchPrefixes: ['/guides/'] },
  { href: '/about', label: 'ABOUT' },
];

// SIGNUP supplies its own font run (the middle cluster inherits font-mono
// from the <ul>); ActiveLink prepends it to the link/active class.
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
