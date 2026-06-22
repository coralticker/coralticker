// scripts/run_email_digest.ts
//
// MANUAL RE-FIRE of the production daily email digest — for the days the Vercel
// cron (/api/cron/email-digest at 13:00 UTC) silently doesn't fire. Calls the
// SAME runEmailDigest() the cron route calls, against the live recipient list.
//
// This is the real send (unlike send_test_digest.ts, which bypasses the list and
// sends one copy to an override address). There is NO idempotency guard in
// runEmailDigest — only run this when the day's digest genuinely did not go out.
//
// Run (creds load from .env via node --env-file; never echoed to stdout):
//   node --env-file=.env --experimental-strip-types scripts/run_email_digest.ts --dry   # counts only, no send
//   node --env-file=.env --experimental-strip-types scripts/run_email_digest.ts         # REAL send
//
// --dry unsets RESEND_API_KEY in-process so runEmailDigest takes its keyless
// dry-run path: it still runs the live row + recipient queries and reports the
// counts, but sends nothing. Use it to confirm the blast size first.

import { runEmailDigest } from '../lib/email/digest.ts';

const dry = process.argv.includes('--dry');
if (dry) {
  delete process.env.RESEND_API_KEY; // force the keyless dry-run path
}

const result = await runEmailDigest(new Date());
console.log(`[run_email_digest${dry ? ' --dry' : ''}]`, JSON.stringify(result));
