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

import { getNeonSql } from '@/lib/db/neon';
import { isEmailSignupSource } from '@/types/email-signups';

export type SignupActionResult =
  | { ok: true; alreadySubscribed: boolean }
  | { ok: false; error: string };

const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const VALIDATION_ERROR = "That doesn't look like an email address.";
const DB_ERROR = "Something's off. Try again in a moment.";

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

  // Statement 1: INSERT. Returns from the catch block on unique_violation;
  // any other error bubbles up to the outer catch as a generic DB_ERROR.
  try {
    await sql`
      INSERT INTO email_signups (email, source)
      VALUES (${email}, ${rawSource})
    `;
    return { ok: true, alreadySubscribed: false };
  } catch (err: unknown) {
    // 23505 = Postgres unique_violation. The lower(email) functional index
    // backstops duplicate signups; existing row tells us active vs. unsubscribed.
    const code = (err as { code?: string }).code;
    if (code !== '23505') {
      return { ok: false, error: DB_ERROR };
    }
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
  try {
    await sql`
      UPDATE email_signups
      SET unsubscribed_at = NULL,
          subscribed_at = ${new Date().toISOString()}
      WHERE id = ${existing.id}
    `;
  } catch {
    return { ok: false, error: DB_ERROR };
  }

  return { ok: true, alreadySubscribed: false };
}
