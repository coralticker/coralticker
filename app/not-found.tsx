// Root-level 404 catch-all for unknown routes — this is an unknown-URL surface
// (the user typed/clicked a path that doesn't exist), distinct from
// app/coral/[slug]/not-found.tsx (unknown slug) and
// app/vendor/[slug]/not-found.tsx (vendor not in active list).
//
// Voice: "I" carve-out gap-moment — third-person here reads as brand-protective
// hedge; first-person owns the gap. The not-built-that-route framing is the
// honest builder admission.

import type { Metadata } from 'next';
import { NotFoundShell } from '@/components/ui/not-found-shell';

export const metadata: Metadata = {
  title: 'Page not found', // suffix via root title.template
  description:
    "I don't have anything at that address — probably a mistyped or stale link.",
};

export default function NotFound() {
  return (
    <NotFoundShell
      title="That page isn't here."
      body="I don't have anything at that address — probably a mistyped or stale link."
      backHref="/new"
      backLabel="← back to new arrivals"
    />
  );
}
