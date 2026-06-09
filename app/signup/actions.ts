'use server';

// §4.6 — /signup Server Action.
//
// Receives FormData from <SignupForm>; validates email format + source ENUM;
// writes into email_signups per architecture-v1.md §1.9.1 with re-subscribe
// semantics for previously-unsubscribed rows.
//
// Returns SignupActionResult discriminated union — site.md §4.6 contract is
// payload-only conceptually, but useActionState's wire-shape threads
// prev-state as first arg.
//
// CTK-043 cut-4 (2026-05-16): migrated from supabase-js to
// @neondatabase/serverless. The 3-statement INSERT → SELECT (on 23505) →
// UPDATE flow is preserved verbatim; pg surfaces the unique_violation
// SQLSTATE as `err.code === '23505'` the same way supabase-js did. Folding
// to ON CONFLICT DO UPDATE is out of scope this cut (recoverable later).

import { after } from 'next/server';
import { getNeonSql } from '@/lib/db/neon';
import { isEmailSignupSource } from '@/types/email-signups';
import { generate } from '@/lib/email/token';
import { sendEmail } from '@/lib/email/send';
import { confirmEmail } from '@/lib/email/templates/confirm-email';

export type SignupActionResult =
  | { ok: true; alreadySubscribed: boolean }
  | { ok: false; error: string };

const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const VALIDATION_ERROR = "That doesn't look like an email address.";
const DB_ERROR = "Something's off. Try again in a moment.";

// Best-effort confirm send (D-3), shared by the fresh-INSERT and re-subscribe
// paths. sendEmail is self-catching and never throws — a Resend failure logs +
// alerts the operator channel internally but never fails the capture. Deferred
// via after() at the call sites so it runs post-response, off the Tier-1B
// signup hot path; {sent} is ignored either way (capture is the contract).
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

  const sql = getNeonSql();

  // Statement 1: INSERT. App-mints the per-row token (CTK-016 D-1), overriding
  // the 0037 gen_random_uuid()::text default (the default is RETAINED as the
  // live-path safety net — never dropped). RETURNING token reads back what
  // actually landed. On unique_violation (23505) the row already exists; fall
  // through to the re-subscribe SELECT/UPDATE. Only DB work lives in this try —
  // the confirm-email send happens after it resolves so a (self-catching) send
  // can never be mistaken for a DB error.
  const token = generate();
  let insertedToken: string | null = null;
  try {
    const rows = (await sql`
      INSERT INTO email_signups (email, source, token)
      VALUES (${email}, ${rawSource}, ${token})
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

  // Statement 2: SELECT existing row to branch on subscription status.
  let existing: { id: number; unsubscribed_at: string | null } | null = null;
  try {
    const rows = (await sql`
      SELECT id, unsubscribed_at
      FROM email_signups
      WHERE email = ${email}
      LIMIT 1
    `) as unknown as { id: number; unsubscribed_at: string | null }[];
    existing = rows[0] ?? null;
  } catch {
    return { ok: false, error: DB_ERROR };
  }

  if (existing === null) {
    return { ok: false, error: DB_ERROR };
  }

  if (existing.unsubscribed_at === null) {
    return { ok: true, alreadySubscribed: true };
  }

  // Statement 3: re-subscribe — clear unsubscribed_at + bump subscribed_at.
  // RETURNING token REUSES the row's existing token — do NOT re-mint: re-minting
  // would invalidate any confirm/unsubscribe link already sitting in this
  // person's inbox. Send happens after the DB try resolves (DB-only try).
  let resubToken: string | undefined;
  try {
    const rows = (await sql`
      UPDATE email_signups
      SET unsubscribed_at = NULL,
          subscribed_at = ${new Date().toISOString()}
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
