// /corals — flat alphabetical index of named corals with at-least-one
// in-window listing per CTK-057. Composition mirrors /vendors (CTK-055):
// max-w-3xl frame, prose-register H1, Suspense + skeleton, py-3 rows.
//
// Dormancy gate: getAllNamedCoralsWithListings() restricts to corals with an
// in-window in-stock listing — rendered rows route to a populated
// /coral/[slug] DEFAULT render per the Default-render parity rule
// (branding-guide §"State markers", CTK-126 D-2), modulo the 600/300 TTL
// skew window documented at the helper's header; vendor-side deliberately
// stricter (see the helper's header comment).
//
// CTK-126: "About this list." block below the row stack — scope caveat +
// two-layer match provenance + request-a-coral/correction invite, one block
// per the /brand-manager one-block ruling. Copy verbatim from
// .claude/plans/tickets/CTK-126/copy/round-1/corals-about-block-rev1.md
// (rev1 LOCKED 2026-06-05 incl. Jon third-beat amendment). First-person per
// the provenance-moments "I"-carve-out flavor.
// v1-minimal: no enrichment, no eyebrow, no vendor counts (CTK-009 Phase 3
// charter). Single internal link per row — /coral/[slug] hero owns the
// vendor CTA, so no outbound pair (deviation from the /vendors two-link row
// is scope, not drift). Row underline treatment drift-added to the /vendors
// hover-only carve-out per /brand-manager 2026-06-04 (branding-guide §"Color
// system" carve-out entry).
//
// ISR revalidate = 600 per site.md §1.2 + /vendors precedent.

import type { Metadata } from 'next';
import { Suspense } from 'react';
import Link from 'next/link';
import { getAllNamedCoralsWithListings } from '@/lib/queries/named-corals';
import { CORAL_RECENCY_DAYS } from '@/lib/queries/listings';

export const revalidate = 600;

export const metadata: Metadata = {
  title: 'Corals — CoralTicker',
  description:
    'Named corals recently listed across the vendors CoralTicker tracks. Direct links to availability.',
  alternates: {
    canonical: '/corals',
  },
};

const SKELETON_ROW_COUNT = 6;

// Defensive zero-row branch — fires only if none of the seeded corals has an
// in-window listing. Copy locked /brand-manager 2026-06-04 (gap-moment
// "I"-voice carve-out; derive-from-constant sanctioned as the alternate path
// at the same lock). The "7 days" string derives from CORAL_RECENCY_DAYS —
// the same constant getAllNamedCoralsWithListings windows on — so the copy
// moves with the window by construction.
const EMPTY_FALLBACK = `No named corals listed in the last ${CORAL_RECENCY_DAYS} days. When one lists, I'll surface it here.`;

async function CoralList() {
  const corals = await getAllNamedCoralsWithListings();

  if (corals.length === 0) {
    return (
      <p role="status" className="text-base text-ink py-6">
        {EMPTY_FALLBACK}
      </p>
    );
  }

  return (
    <ul>
      {corals.map((coral) => (
        <li key={coral.slug} className="py-3">
          <Link
            href={`/coral/${coral.slug}`}
            className="text-base font-bold hover:underline focus-visible:underline underline-offset-[3px] decoration-1"
          >
            {coral.canonical_name}
          </Link>
        </li>
      ))}
    </ul>
  );
}

function CoralListSkeleton() {
  return (
    <ul role="status" aria-busy="true" aria-label="Loading corals">
      {Array.from({ length: SKELETON_ROW_COUNT }).map((_, i) => (
        <li key={i} className="py-3">
          <span
            aria-hidden="true"
            className="inline-block h-4 w-40 align-middle bg-ink/15 rounded-sm animate-pulse"
          />
        </li>
      ))}
    </ul>
  );
}

// Discord invite reads the env var, not a hardcoded literal (Jon call,
// rev1 copy file): per-surface invites are DELIBERATE — Discord's native
// invite tracking gives per-surface join attribution, so do NOT consolidate
// with the /about invite (social-links.tsx). The var lives in .env locally
// and the Vercel project env for deploys (.env is gitignored, never reaches
// the build); /corals is static/ISR so the value inlines at build — invite
// rotation needs a redeploy/revalidate, acceptable for a stable invite.
// <SocialLinks> primitive promotion still waits for its second-surface
// trigger per branding-guide L99 — this is a prose link, not the primitive.
//
// FEEDBACK invite, not DROPS (CTK-126 close micro-session 2026-06-05): the
// block's ask is additions + corrections, so the link targets the #feedback
// channel invite. DISCORD_DROPS_INVITE_URL stays valid for drop-watching
// surfaces (no consumer today).
//
// Throw-on-missing per the lib/db/neon.ts:24 idiom (CTK-126 fold,
// /code-review #2 Tier 1B): a missing var fails the build loudly instead of
// shipping a dead Discord anchor (href={undefined} renders a non-link).
const DISCORD_FEEDBACK_INVITE_URL_RAW = process.env.DISCORD_FEEDBACK_INVITE_URL;

if (!DISCORD_FEEDBACK_INVITE_URL_RAW) {
  throw new Error('DISCORD_FEEDBACK_INVITE_URL must be set. See .env.example.');
}

const discordInviteUrl: string = DISCORD_FEEDBACK_INVITE_URL_RAW;

function AboutThisList() {
  return (
    <section id="about-this-list" className="mt-12">
      {/* Sentence-case header + 1px under-rule per branding-guide
          §"Section transitions on content surfaces". */}
      <h2 className="text-sm font-bold pb-2 mb-2 border-b border-ink/20">
        About this list.
      </h2>
      <div className="text-base leading-relaxed space-y-4 pt-2">
        <p>
          These are corals people hunt by name &mdash; a curated list, not
          everything I track.{' '}
          <Link href="/new" className="underline">
            New arrivals
          </Link>{' '}
          and{' '}
          <Link href="/vendors" className="underline">
            vendor pages
          </Link>{' '}
          have the rest.
        </p>
        <p>
          The origin shown for each coral comes from a list I researched by
          hand, against vendor pages and hobbyist forums. Listings are matched
          to that list by name. The vendors don&apos;t confirm those matches
          &mdash; I infer them.
        </p>
        <p>
          If a coral belongs here &mdash; or I&apos;ve got one wrong &mdash;
          tell me on{' '}
          <a
            href={discordInviteUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="underline"
          >
            Discord
          </a>
          .
        </p>
      </div>
    </section>
  );
}

export default function CoralsPage() {
  return (
    <main className="px-6 py-12 max-w-3xl mx-auto">
      <h1 className="text-3xl md:text-4xl font-bold mb-8">Corals.</h1>
      <Suspense fallback={<CoralListSkeleton />}>
        <CoralList />
      </Suspense>
      <AboutThisList />
    </main>
  );
}
