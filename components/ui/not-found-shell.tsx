// Shared not-found / gap-moment surface — thin <PageShell as="section">
// specialization extracted at CTK-077 (F-S7-6). The three 404 surfaces
// (app/not-found.tsx, app/coral/[slug]/not-found.tsx, app/vendor/[slug]/
// not-found.tsx) repeated the same <main> + H1 + body + back-link shape; this
// primitive enforces it structurally.
//
// Typography canon ratified /brand-manager 2026-06-11 Element 2 (served-neutral
// — already byte-identical across all three surfaces): H1 text-3xl md:text-4xl
// font-bold mb-6, body text-base leading-relaxed mb-8, back-link text-base
// wrapping a className="underline" <Link>. The back-link is underline-at-rest
// (branding-guide.md L243) — the singleton back-link is in the L245 carve-out's
// exclusion list, so it does NOT take the /vendors+/corals hover-only
// treatment.
//
// Copy passes through verbatim via title/body/backLabel — the primitive is
// copy-agnostic. The L106/L107/L153 not-found copy normalization stays parked
// at open-items.md (out of CTK-077 scope; /brand-manager Element 4).

import Link from 'next/link';
import type { ReactNode } from 'react';
import { PageShell } from './page-shell';

interface NotFoundShellProps {
  title: string;
  body: ReactNode;
  backHref?: string;
  backLabel?: string;
}

export function NotFoundShell({
  title,
  body,
  backHref = '/',
  backLabel = 'back home',
}: NotFoundShellProps) {
  return (
    <PageShell as="section">
      <h1 className="text-3xl md:text-4xl font-bold mb-6">{title}</h1>
      <p className="text-base leading-relaxed mb-8">{body}</p>
      <p className="text-base">
        <Link href={backHref} className="underline">
          {backLabel}
        </Link>
      </p>
    </PageShell>
  );
}
