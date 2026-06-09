// One-off live send-test for the CTK-016 confirm email (D-2: transport + render).
//
// Sends ONE real confirm email through Resend to the recipient passed as argv,
// using the production code path (confirmEmail() body -> sendEmail() transport).
// Validates send.coralticker.com domain auth (SPF/DKIM/DMARC alignment), the
// drops@send.coralticker.com from-address, and the email body rendering in a
// real inbox.
//
// SCOPE: transport + render only. The confirm CTA in the email points at the
// PRODUCTION apex (https://coralticker.com/confirm?t=...). This script does NOT
// write an email_signups row, so clicking the CTA won't round-trip until the
// Leg-4 routes are deployed with a matching row. The full signup -> email ->
// confirm e2e is the post-deploy test.
//
// Run (recipient = your own inbox):
//   node --experimental-strip-types scripts/send_test_confirm_email.ts you@example.com
//
// RESEND_API_KEY is read from .env at the repo root (gitignored) — never passed
// on the command line, never printed. If unset, sendEmail() dry-runs
// ({sent:false}, no network).
//
// SECRET DISCIPLINE: this script prints ONLY {to, subject, sent}. Never the key,
// never the html body (which carries the token). Safe to run with output visible.

import { readFileSync } from 'node:fs';
import { generate } from '../lib/email/token.ts';
import { sendEmail } from '../lib/email/send.ts';
import { confirmEmail } from '../lib/email/templates/confirm-email.ts';

// Minimal .env loader: fills process.env from the repo-root .env WITHOUT printing
// any value. Only sets keys not already present in the ambient environment.
function loadDotenv(): void {
  let raw: string;
  try {
    raw = readFileSync(new URL('../.env', import.meta.url), 'utf8');
  } catch {
    return; // no .env — rely on the ambient environment
  }
  for (const line of raw.split('\n')) {
    const m = line.match(/^\s*([A-Za-z0-9_]+)\s*=\s*(.*)\s*$/);
    if (!m) continue;
    const key = m[1];
    const val = m[2];
    if (key === undefined || val === undefined) continue;
    if (process.env[key] === undefined) {
      process.env[key] = val.replace(/^["']|["']$/g, '');
    }
  }
}

// RFC 2606 / 6761 reserved + common test TLDs — these have no real mailbox and
// only ever HARD-BOUNCE, which dings a fresh sending domain's reputation. Refuse
// them so a typo can never send a real bounce-bound message.
const RESERVED_RECIPIENT =
  /@(localhost|example\.(com|org|net)|[^@]*\.(example|invalid|test|localhost))$/i;

async function main(): Promise<void> {
  const args = process.argv.slice(2);
  const dryRun = args.includes('--dry-run');
  const to = args.find((a) => !a.startsWith('--'));

  if (!to) {
    console.error(
      'usage: node --experimental-strip-types scripts/send_test_confirm_email.ts <recipient-email> [--dry-run]',
    );
    process.exit(1);
  }

  if (RESERVED_RECIPIENT.test(to)) {
    console.error(
      `refusing ${to}: reserved/test domains have no mailbox and only hard-bounce. Use a real inbox.`,
    );
    process.exit(1);
  }

  // --dry-run: genuine keyless verification — do NOT load .env, and force the
  // key unset so sendEmail() short-circuits to {sent:false} with NO network call.
  // Also unset VERCEL_ENV so a prod-flagged shell can't trip send.ts's
  // keyless-in-production guard and fire a false operator alert on a dry-run.
  // Without this flag the script loads the real key from .env and SENDS FOR REAL.
  if (dryRun) {
    delete process.env.RESEND_API_KEY;
    delete process.env.VERCEL_ENV;
  } else {
    loadDotenv();
  }

  const token = generate();
  const { subject, html } = confirmEmail(token);

  const { sent } = await sendEmail({ to, subject, html });
  console.log(JSON.stringify({ to, subject, sent }));

  if (!sent) {
    console.error(
      'sent:false — RESEND_API_KEY is unset (dry-run) OR the send failed. ' +
        'If a key IS set, the failure detail is in the error log above.',
    );
    process.exit(1);
  }
  console.log('sent:true — check the recipient inbox (and spam) for "Confirm your email."');
}

main().catch((err) => {
  console.error('send-test threw:', err);
  process.exit(1);
});
