// /corals — flat alphabetical index of named corals with at-least-one
// in-window listing per CTK-057. Composition mirrors /vendors (CTK-055):
// max-w-3xl frame, prose-register H1, Suspense + skeleton; rows carry the
// listing-row divider treatment (py-6 border-b border-line, CTK-140 rider —
// parity with ListingRowFrame + /search rows; /vendors fixed same commit).
//
// Dormancy gate: getAllNamedCoralsWithListings() restricts to corals with an
// in-window in-stock listing — rendered rows route to a populated
// /coral/[slug] DEFAULT render per the Default-render parity rule
// (branding-guide §"State markers", CTK-126 D-2). Cadence matched to the
// destination's 300 at CTK-128 (d) — skew bound + rationale live at the
// helper's header; vendor-side deliberately stricter (same header).
//
// CTK-126: "About this list." block below the row stack — scope caveat +
// two-layer match provenance + request-a-coral/correction invite, one block
// per the /brand-manager one-block ruling. Copy verbatim from
// .claude/plans/tickets/CTK-126/copy/round-1/corals-about-block-rev1.md
// (rev1 LOCKED 2026-06-05 incl. Jon third-beat amendment). First-person per
// the provenance-moments "I"-carve-out flavor.
// v1-minimal: no eyebrow, no vendor counts (CTK-009 Phase 3 charter).
// CTK-139 exception: representative thumbnails pulled forward from the
// CTK-009 enrichment park per external first-look feedback 2026-06-11,
// Jon-ratified — 96×96 slot per the ListingRowFrame convention, image =
// newest in-window in-stock listing with an image (null renders the bare
// bg-wash box). CTK-140 exception: identity data row (Type. — Origin.)
// below the name per the locked field-set canon (branding-guide §"Em-dash
// data row format" → "/corals index-row field-set") — the destination
// lineage row's leading pair, same render rules via buildLineageFields;
// vendor-count / last-seen / Year. stay canon-rejected (re-open trigger
// lives in the canon entry). The /vendors mirror divergence (thumbs here,
// none there) is scope, not drift. Single internal link per row —
// /coral/[slug] hero owns the vendor CTA, so no outbound pair (deviation
// from the /vendors two-link row is scope, not drift). Row underline
// treatment drift-added to the /vendors hover-only carve-out per
// /brand-manager 2026-06-04 (branding-guide §"Color system" carve-out
// entry); since CTK-140 it scopes to the name span via group-hover — the
// data row keeps the destination's text-sm regular register (canon register
// split), so neither the link's bold nor its hover underline may reach it.
//
// ISR revalidate = 300 (CTK-128 (d) retune) — tandem with
// CORALS_INDEX_REVALIDATE_S at lib/queries/named-corals.ts; this literal
// can't import it (Next statically analyzes segment config), so
// scripts/coral-predicate-coupling.test.ts pins the pair. Skew bound +
// /vendors-divergence rationale at the helper's header.

import type { Metadata } from 'next';
import { Suspense } from 'react';
import Link from 'next/link';
import { getAllNamedCoralsWithListings } from '@/lib/queries/named-corals';
import { CORAL_RECENCY_DAYS } from '@/lib/queries/listings';
import { getRequiredEnv } from '@/lib/env';
import { buildLineageFields } from '@/lib/format/lineage-fields';
import { DataRow } from '@/components/ui/data-row';
import { ThumbSlot } from '@/components/ui/thumb-slot';

export const revalidate = 300;

export const metadata: Metadata = {
  title: 'Corals', // suffix via root title.template
  description:
    'Named corals recently listed across the vendors CoralTicker tracks. Direct links to availability.',
  alternates: {
    canonical: '/corals',
  },
  openGraph: { url: '/corals', siteName: 'CoralTicker', type: 'website', locale: 'en_US' },
  twitter: { card: 'summary' },
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
      {corals.map((coral) => {
        const fields = buildLineageFields(coral);
        return (
          <li key={coral.slug} className="py-6 border-b border-line">
            <Link
              href={`/coral/${coral.slug}`}
              className="group flex gap-4"
            >
              {/* Shared 96×96 slot (ThumbSlot). alt="" — decorative: the NAME
                  SPAN ALONE carries the link's accessible name (/lead-frontend
                  ruling 2026-06-11; non-empty alt would double-announce per
                  row), so ThumbSlot's aria-hidden rule keeps the slot hidden
                  here regardless of image. The data row below is aria-hidden
                  under the same ruling — see its comment. */}
              <ThumbSlot src={coral.image_url} alt="" />
              <div className="min-w-0">
                {/* Bold + hover-underline live on the name span, not the link:
                    the data row below must keep the destination's text-sm
                    regular register (canon register split), and an underline
                    on the flex-container link would propagate into it. group-
                    hover keeps the whole row as the hover surface. */}
                <span className="block text-base font-bold leading-snug group-hover:underline group-focus-visible:underline underline-offset-[3px] decoration-1">
                  {coral.canonical_name}
                </span>
                {/* Length guard, not a truthy-null guard: a bare <DataRow>
                    renders its wrapper div on an empty array — a both-null
                    row must render no line and no phantom height (canon:
                    never an empty dash line). Matches the /coral/[slug]
                    consumer pattern.
                    aria-hidden — the row sits INSIDE the link, and without it
                    every links-rotor entry reads "Name Type. X Origin. Y"
                    (only the em-dash separator is hidden inside <DataRow>).
                    Same principle as the alt="" ruling above: the name span
                    alone is the accessible name; the lineage pair is
                    duplicative-within-link, repeated link-free one click away
                    on /coral/[slug] (CTK-140 /code-review fold). */}
                {fields.length > 0 ? (
                  <div className="mt-2" aria-hidden="true">
                    <DataRow fields={fields} />
                  </div>
                ) : null}
              </div>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

function CoralListSkeleton() {
  return (
    <ul role="status" aria-busy="true" aria-label="Loading corals">
      {Array.from({ length: SKELETON_ROW_COUNT }).map((_, i) => (
        <li key={i} className="py-6 border-b border-line">
          <span className="flex gap-4" aria-hidden="true">
            <span className="shrink-0 w-24 h-24 bg-wash animate-pulse" />
            {/* Two bone lines — name + data row — so the loading shape
                matches the loaded shape (CTK-140 D3 skeleton parity; CLS
                guard). */}
            <span className="flex flex-col gap-2">
              <span className="h-4 w-40 bg-wash rounded-sm animate-pulse" />
              <span className="h-3.5 w-56 bg-wash rounded-sm animate-pulse" />
            </span>
          </span>
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
// getRequiredEnv: a missing var fails the build loudly instead of shipping
// a dead Discord anchor (href={undefined} renders a non-link — the
// CTK-126 /code-review #2 defect).
const discordInviteUrl = getRequiredEnv('DISCORD_FEEDBACK_INVITE_URL');

function AboutThisList() {
  return (
    <section id="about-this-list" className="mt-12">
      {/* Sentence-case header + 1px under-rule per branding-guide
          §"Section transitions on content surfaces". */}
      <h2 className="text-sm font-bold pb-2 mb-2 border-b border-line">
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
