// types/email-signups.ts
//
// Mirrors architecture-v1.md §1.9.1 ENUM email_signup_source.
// Source of truth is the Postgres ENUM; this type is the TS-side checked mirror.
// New surfaces ship via ALTER TYPE migration + a parallel addition here.

export type EmailSignupSource =
  | 'homepage'
  | 'footer'
  | 'new_drops_page'
  | 'coral_page'
  | 'vendor_page'
  | 'other';

export const EMAIL_SIGNUP_SOURCES: readonly EmailSignupSource[] = [
  'homepage',
  'footer',
  'new_drops_page',
  'coral_page',
  'vendor_page',
  'other',
] as const;

export function isEmailSignupSource(value: unknown): value is EmailSignupSource {
  return typeof value === 'string' && (EMAIL_SIGNUP_SOURCES as readonly string[]).includes(value);
}
