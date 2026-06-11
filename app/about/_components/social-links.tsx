// §4.7 <SocialLinks>
// Single-view co-located primitive per site.md §1.1; /about-only at v1.
// Layout A locked 2026-05-18 (CTK-040 Q-4): Discord + R2R, launch-confirmed.
// Stroke-throughout Lucide-style icons at 20px, ink throughout (no forest);
// underline-only label affordance on hover + focus-visible per
// branding-guide.md §"Color system" link rule. Promotes to components/ui/
// only when a second surface consumes (Phase 4 /signup/confirmed).

import type { ReactNode } from 'react';
import { getRequiredEnv } from '@/lib/env';

// CTK-126 D-5(b) — hardcoded invite literal migrated to a per-surface env
// var (the old DbGnQTfzC invite was expiring 2026-06-18; Jon minted a
// permanent replacement 2026-06-05). Per-surface vars are DELIBERATE —
// Discord's native invite tracking gives per-surface join attribution; do
// NOT consolidate with the /corals invite (DISCORD_FEEDBACK_INVITE_URL).
const DISCORD_ABOUT_INVITE_URL = getRequiredEnv('DISCORD_ABOUT_INVITE_URL');

type SocialLink = {
  href: string;
  label: string;
  ariaLabel: string;
  iconPaths: ReactNode;
};

const links: SocialLink[] = [
  {
    href: DISCORD_ABOUT_INVITE_URL,
    label: 'Discord',
    ariaLabel: 'Discord',
    iconPaths: (
      <>
        <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z" />
        <circle cx="9.5" cy="11.5" r="0.8" fill="currentColor" stroke="none" />
        <circle cx="14.5" cy="11.5" r="0.8" fill="currentColor" stroke="none" />
      </>
    ),
  },
  {
    href: 'https://www.reef2reef.com/',
    label: 'Reef2Reef',
    ariaLabel: 'Reef2Reef forum',
    iconPaths: (
      <>
        <path d="M14 9a2 2 0 0 1-2 2H6l-4 4V4c0-1.1.9-2 2-2h8a2 2 0 0 1 2 2v5z" />
        <path d="M18 9h2a2 2 0 0 1 2 2v11l-4-4h-6a2 2 0 0 1-2-2v-1" />
      </>
    ),
  },
];

export function SocialLinks() {
  return (
    <ul
      aria-label="Social channels"
      className="flex flex-wrap items-center gap-4 list-none p-0"
    >
      {links.map((link) => (
        <li key={link.href} className="inline-flex items-center">
          <a
            href={link.href}
            aria-label={link.ariaLabel}
            className="group inline-flex items-center gap-2 text-ink py-1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-ink focus-visible:outline-offset-4"
          >
            <svg
              aria-hidden="true"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth={1.75}
              strokeLinecap="round"
              strokeLinejoin="round"
              className="w-5 h-5 shrink-0"
            >
              {link.iconPaths}
            </svg>
            <span className="decoration-1 underline-offset-[3px] group-hover:underline group-focus-visible:underline">
              {link.label}
            </span>
          </a>
        </li>
      ))}
    </ul>
  );
}
