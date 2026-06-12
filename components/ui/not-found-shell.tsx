// Shared not-found / gap-moment surface — thin <PageShell as="section">
// specialization. The back-link is underline-at-rest — the singleton back-link
// is in the carve-out's exclusion list, so it does NOT take the
// /vendors+/corals hover-only treatment.

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
