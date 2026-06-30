// scripts/run_email_digest.ts
//
// MANUAL RE-FIRE of the production daily email digest — for the days the Vercel
// cron silently doesn't fire (and the daily channel-consolidation step in
// discord-digest.yml — CTK-218). Calls the SAME runEmailDigest() the cron route
// calls, against the live recipient list.
//
// This is the real send (unlike send_test_digest.ts, which bypasses the list and
// sends one copy to an override address). runEmailDigest now carries a fire-once
// idempotency guard (CTK-218): a second same-UTC-day run no-ops with
// status=already-sent. Pass --force to re-send anyway (the legit "cron missed,
// re-fire today" case) — force both bypasses the row guard AND appends a per-run
// nonce to the Resend Idempotency-Key, so the re-send actually delivers instead of
// deduping against the original send inside Resend's 24h window.
//
// Run (creds load from .env via node --env-file; never echoed to stdout):
//   node --env-file=.env --experimental-strip-types scripts/run_email_digest.ts --dry     # counts only, no send
//   node --env-file=.env --experimental-strip-types scripts/run_email_digest.ts           # REAL send (no-op if already sent today)
//   node --env-file=.env --experimental-strip-types scripts/run_email_digest.ts --force    # REAL send, bypass the fire-once guard
//
// --dry unsets RESEND_API_KEY in-process so runEmailDigest takes its keyless
// dry-run path: it still runs the live row + recipient queries and reports the
// counts, but sends nothing. --dry also bypasses the fire-once guard (it has no
// side effects, so it should always report the blast size even on a day already
// sent). Use it to confirm the blast size first.

import { runEmailDigest } from '../lib/email/digest.ts';

const dry = process.argv.includes('--dry');
const force = process.argv.includes('--force');
if (dry) {
  delete process.env.RESEND_API_KEY; // force the keyless dry-run path
}

// --dry never sends or records, so bypassing the guard for it is harmless and keeps
// the count report working on an already-sent day.
const result = await runEmailDigest(new Date(), { force: force || dry });
console.log(`[run_email_digest${dry ? ' --dry' : ''}${force ? ' --force' : ''}]`, JSON.stringify(result));
