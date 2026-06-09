// /confirm?t=<token> — CTK-016 Leg 4 double-opt-in confirmation.
//
// The ONLY writer of email_signups.confirmed_at (plan §Context): the notifier
// filters confirmed_at IS NOT NULL AND unsubscribed_at IS NULL, so until this
// route runs, every captured row is DOI-pending and the digest reaches nobody.
//
// Sets confirmed_at = now() for the row matching the opaque token (CTK-016 D-1;
// one token per row, route scopes the purpose), then redirects to the existing
// /signup/confirmed landing ("You're subscribed.").
//
// IDEMPOTENT: the UPDATE is gated `confirmed_at IS NULL`, so a re-click sets
// nothing (timestamp frozen at first confirm) but still lands the same page.
// Already-confirmed and matched-now are indistinguishable to the visitor — both
// see "You're subscribed.", which is correct in both cases.
//
// Unlike /unsubscribe, /confirm acts on GET: a prefetch-bot auto-confirming only
// completes the opt-in the signer already asked for (low harm), whereas a
// prefetch-bot auto-UNSUBSCRIBING is destructive — hence the GET/POST split is
// applied to /unsubscribe only (plan §Leg 4). Known minor DOI weakness, accepted.

import { NextResponse } from 'next/server';
import { getNeonSql } from '@/lib/db/neon';

export const dynamic = 'force-dynamic';

export async function GET(request: Request): Promise<NextResponse> {
  const url = new URL(request.url);
  const token = url.searchParams.get('t');

  // No token = not a real confirm click (crawler / malformed link). Land neutral
  // home rather than falsely assert "You're subscribed."
  if (!token) {
    return NextResponse.redirect(new URL('/', url.origin), 307);
  }

  try {
    const sql = getNeonSql();
    await sql`
      UPDATE email_signups
      SET confirmed_at = now()
      WHERE token = ${token} AND confirmed_at IS NULL
    `;
  } catch (err) {
    // Surface in the Vercel function log. The link stays valid — a re-click
    // retries the write — so we still land the confirmed page rather than
    // dead-ending the click on a transient DB error. (An invalid/expired-token
    // and confirm-DB-error UX surface is a flagged gap for /brand-manager.)
    console.error('confirm: confirmed_at UPDATE failed', err);
  }

  return NextResponse.redirect(new URL('/signup/confirmed', url.origin), 307);
}
