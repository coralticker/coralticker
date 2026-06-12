// Dormancy gate: getAllNamedCoralsWithListings() restricts to corals with an
// in-window in-stock listing, so rendered rows always route to a populated
// /coral/[slug] DEFAULT render.
//
// Thumbnails: image = newest in-window in-stock listing with an image (null
// renders the bare bg-wash box). Single internal link per row — /coral/[slug]
// hero owns the vendor CTA, so no outbound pair. Hover underline scopes to the
// name span via group-hover so it can't reach the data row, which must keep
// the destination's text-sm regular register (canon register split).
//
// ISR revalidate = 300 runs in tandem with CORALS_INDEX_REVALIDATE_S at
// lib/queries/named-corals.ts; this literal can't import it (Next statically
// analyzes segment config), so scripts/coral-predicate-coupling.test.ts pins
// the pair.

import type { Metadata } from 'next';
import { Suspense } from 'react';
import Link from 'next/link';
import { getAllNamedCoralsWithListings } from '@/lib/queries/named-corals';
import { CORAL_RECENCY_DAYS } from '@/lib/queries/listings';
import { getRequiredEnv } from '@/lib/env';
import { buildLineageFields } from '@/lib/format/lineage-fields';
import { DataRow } from '@/components/ui/data-row';
import { ThumbSlot, THUMB_SLOT_BOX } from '@/components/ui/thumb-slot';
import { PageShell } from '@/components/ui/page-shell';
import { PageH1 } from '@/components/ui/page-h1';
import { SectionHeader } from '@/components/ui/section-header';

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
// in-window listing. The "7 days" string derives from CORAL_RECENCY_DAYS — the
// same constant getAllNamedCoralsWithListings windows on — so the copy moves
// with the window by construction.
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
              {/* alt="" — decorative: the NAME SPAN ALONE carries the link's
                  accessible name (non-empty alt would double-announce per
                  row), so ThumbSlot's aria-hidden rule keeps the slot hidden
                  here regardless of image. The data row below is aria-hidden
                  under the same rule. */}
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
                    never an empty dash line).
                    aria-hidden — the row sits INSIDE the link, and without it
                    every links-rotor entry reads "Name Type. X Origin. Y"
                    (only the em-dash separator is hidden inside <DataRow>).
                    Same principle as the alt="" rule above: the name span
                    alone is the accessible name; the lineage pair is
                    duplicative-within-link, repeated link-free one click away
                    on /coral/[slug]. */}
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
            <span className={`${THUMB_SLOT_BOX} animate-pulse`} />
            {/* Two bone lines — name + data row — so the loading shape
                matches the loaded shape (CLS guard). */}
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

// Per-surface invites are DELIBERATE — Discord's native invite tracking gives
// per-surface join attribution, so do NOT consolidate with the /about invite
// (social-links.tsx). /corals is static/ISR so the value inlines at build —
// invite rotation needs a redeploy/revalidate, acceptable for a stable invite.
//
// FEEDBACK invite, not DROPS: the block's ask is additions + corrections, so
// the link targets the #feedback channel invite.
//
// getRequiredEnv: a missing var fails the build loudly instead of shipping a
// dead Discord anchor (href={undefined} renders a non-link).
const discordInviteUrl = getRequiredEnv('DISCORD_FEEDBACK_INVITE_URL');

function AboutThisList() {
  return (
    <section id="about-this-list" className="mt-12">
      <SectionHeader>
        About this list.
      </SectionHeader>
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
    <PageShell as="section">
      <PageH1 className="mb-8">Corals.</PageH1>
      <Suspense fallback={<CoralListSkeleton />}>
        <CoralList />
      </Suspense>
      <AboutThisList />
    </PageShell>
  );
}
