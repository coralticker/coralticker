// app/not-found.tsx — root-level 404 catch-all for unknown routes.
//
// Fires for any URL that doesn't resolve to a defined route. Surface is
// unknown-URL (the user typed/clicked a path that doesn't exist on
// CoralTicker), not unknown-data — distinct from app/coral/[slug]/not-found.tsx
// (matcher-dormancy / unknown slug) and app/vendor/[slug]/not-found.tsx
// (vendor not in active list).
//
// Voice: "I" carve-out gap-moment per branding-guide.md L102-104 — third-person
// here reads as brand-protective hedge; first-person owns the gap. The
// not-built-that-route framing is the honest builder admission.
//
// Folded in 2026-05-21 per /brand-manager INV-02 pre-first-implementation-session
// gate for CTK-015 (coordination-invariants.md INV-02 checkpoint 1 of 3).

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
