'use server';

import { after } from 'next/server';
import { cookies } from 'next/headers';
import { getNeonSql } from '@/lib/db/neon';
import { isEmailSignupSource, isReferrerChannel } from '@/types/email-signups';
import { generate } from '@/lib/email/token';
import { sendEmail } from '@/lib/email/send';
import { confirmEmail } from '@/lib/email/templates/confirm-email';

export type SignupActionResult =
  | { ok: true; alreadySubscribed: boolean }
  | { ok: false; error: string };

const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const VALIDATION_ERROR = "That doesn't look like an email address.";
const DB_ERROR = "Something's off. Try again in a moment.";

// Best-effort confirm send, shared by the fresh-INSERT and re-subscribe paths.
// sendEmail is self-catching and never throws — a Resend failure logs + alerts
// the operator channel internally but never fails the capture. Deferred via
// after() at the call sites so it runs post-response, off the signup hot path;
// {sent} is ignored either way (capture is the contract).
async function sendConfirm(email: string, token: string): Promise<void> {
  const { subject, html } = confirmEmail(token);
  await sendEmail({ to: email, subject, html });
}

export async function signupAction(
  _prevState: SignupActionResult | null,
  formData: FormData,
): Promise<SignupActionResult> {
  const rawEmail = formData.get('email');
  const rawSource = formData.get('source');

  if (typeof rawEmail !== 'string') {
    return { ok: false, error: VALIDATION_ERROR };
  }
  const email = rawEmail.trim().toLowerCase();
  if (!EMAIL_REGEX.test(email)) {
    return { ok: false, error: VALIDATION_ERROR };
  }

  if (!isEmailSignupSource(rawSource)) {
    return { ok: false, error: DB_ERROR };
  }

  // First-touch channel, stamped by middleware from ?ref=. Independent of source:
  // a homepage signup that arrived via the IG bio link is source=homepage +
  // referrer_channel=ig. Anything off-allowlist (or absent) falls through to NULL
  // — organic/direct, derived as 'direct' at read time, never stored as a literal.
  const rawRef = (await cookies()).get('ct_ref')?.value;
  const referrerChannel = isReferrerChannel(rawRef) ? rawRef : null;

  const sql = getNeonSql();

  // App-mints the per-row token, overriding the gen_random_uuid()::text default
  // (the default is RETAINED as the live-path safety net — never dropped).
  // RETURNING token reads back what actually landed. On unique_violation (23505)
  // the row already exists; fall through to the re-subscribe SELECT/UPDATE. Only
  // DB work lives in this try — the confirm-email send happens after it resolves
  // so a (self-catching) send can never be mistaken for a DB error.
  const token = generate();
  let insertedToken: string | null = null;
  try {
    const rows = (await sql`
      INSERT INTO email_signups (email, source, referrer_channel, token)
      VALUES (${email}, ${rawSource}, ${referrerChannel}, ${token})
      RETURNING token
    `) as unknown as { token: string }[];
    insertedToken = rows[0]?.token ?? token;
  } catch (err: unknown) {
    // 23505 = Postgres unique_violation. The lower(email) functional index
    // backstops duplicate signups; existing row tells us active vs. unsubscribed.
    const code = (err as { code?: string }).code;
    if (code !== '23505') {
      return { ok: false, error: DB_ERROR };
    }
  }

  if (insertedToken !== null) {
    // Fresh signup: fire the confirm send post-response (after()) so the user
    // doesn't wait on the Resend round-trip. const-capture keeps the non-null
    // narrowing inside the deferred closure.
    const tokenToSend = insertedToken;
    after(() => sendConfirm(email, tokenToSend));
    return { ok: true, alreadySubscribed: false };
  }

  // SELECT existing row to branch on subscription status. Projects confirmed_at
  // + token (beyond unsubscribed_at) so the active-row branch below can
  // distinguish a genuinely-subscribed row from a pending-confirmation one and
  // re-send the confirm where needed.
  let existing:
    | { id: number; unsubscribed_at: string | null; confirmed_at: string | null; token: string }
    | null = null;
  try {
    const rows = (await sql`
      SELECT id, unsubscribed_at, confirmed_at, token
      FROM email_signups
      WHERE email = ${email}
      LIMIT 1
    `) as unknown as {
      id: number;
      unsubscribed_at: string | null;
      confirmed_at: string | null;
      token: string;
    }[];
    existing = rows[0] ?? null;
  } catch {
    return { ok: false, error: DB_ERROR };
  }

  if (existing === null) {
    return { ok: false, error: DB_ERROR };
  }

  // Active row (not unsubscribed). Two sub-cases:
  if (existing.unsubscribed_at === null) {
    if (existing.confirmed_at !== null) {
      // Genuinely subscribed + confirmed — true no-op.
      return { ok: true, alreadySubscribed: true };
    }
    // Pending confirmation (signed up, never confirmed): a re-submit almost
    // always means the confirm email was lost (spam/Resend hiccup — never
    // retried). Re-send it (reuse the token so any in-flight link still works)
    // rather than falsely returning "already subscribed" with no recovery — the
    // row never enters fetchRecipients() (confirmed_at IS NOT NULL) until /confirm
    // fires, so the false claim would otherwise be a permanent dead-end.
    // Opportunistic first-touch backfill, mirroring the re-subscribe branch so a
    // pending row isn't the odd one out (legacy NULL rows backfill, this should
    // too). Best-effort: this branch's contract is capture + confirm re-send, so a
    // backfill failure must never surface as DB_ERROR — swallow it. Skipped
    // entirely when there's no channel to write.
    if (referrerChannel !== null) {
      try {
        await sql`
          UPDATE email_signups
          SET referrer_channel = COALESCE(referrer_channel, ${referrerChannel})
          WHERE id = ${existing.id}
        `;
      } catch {
        // opportunistic — never break capture for an attribution backfill
      }
    }
    const tokenToSend = existing.token;
    after(() => sendConfirm(email, tokenToSend));
    return { ok: true, alreadySubscribed: false };
  }

  // Re-subscribe — clear unsubscribed_at + reset confirmed_at + bump
  // subscribed_at. Resetting confirmed_at to NULL forces a fresh double-opt-in:
  // a confirm→unsubscribe→re-subscribe address must re-confirm before
  // re-entering the digest recipient set, which gates on
  // `confirmed_at IS NOT NULL AND unsubscribed_at IS NULL`. Without this reset,
  // clearing unsubscribed_at alone re-admits the address the instant the form is
  // submitted — re-mailing a previously-unsubscribed, unauthenticated address
  // with no fresh opt-in, the highest spam-complaint risk to the sending domain.
  // The reset is unconditional: a never-confirmed row is already NULL, so it's a
  // no-op there. The confirm email sent below (now correct copy — they genuinely
  // must re-confirm) re-admits them only when /confirm sets confirmed_at.
  // RETURNING token REUSES the row's existing token — do NOT re-mint: re-minting
  // would invalidate any confirm/unsubscribe link already sitting in this
  // person's inbox, and the re-confirm link in the new email must match it.
  // Send happens after the DB try resolves (DB-only try).
  // referrer_channel uses COALESCE so a re-subscribe only BACKFILLS a NULL (e.g. a
  // pre-attribution row) — it never overwrites a channel already recorded at
  // first touch.
  let resubToken: string | undefined;
  try {
    const rows = (await sql`
      UPDATE email_signups
      SET unsubscribed_at = NULL,
          confirmed_at = NULL,
          subscribed_at = ${new Date().toISOString()},
          referrer_channel = COALESCE(referrer_channel, ${referrerChannel})
      WHERE id = ${existing.id}
      RETURNING token
    `) as unknown as { token: string }[];
    resubToken = rows[0]?.token;
  } catch {
    return { ok: false, error: DB_ERROR };
  }

  if (resubToken) {
    // Same post-response best-effort send as the fresh-INSERT path.
    const tokenToSend = resubToken;
    after(() => sendConfirm(email, tokenToSend));
  }

  return { ok: true, alreadySubscribed: false };
}
