// lib/email/client.ts
//
// Lazy Resend client singleton. Mirrors lib/db/neon.ts getNeonSql()'s lazy-init
// shape: instantiate on first use, cache in a module-scope nullable.
//
// One deliberate divergence from neon.ts: the API key is read INSIDE getResend()
// at call time, NOT at module scope with throw-on-missing. neon.ts can throw at
// import because NEON_DATABASE_URL is required everywhere the module loads; the
// email module must import cleanly with RESEND_API_KEY unset so the local
// dry-run path (and any build step that imports lib/email/ without sending)
// works keyless (CTK-016 dependency note). The throw lands at send time, where a
// missing key is an actual error — but send.ts short-circuits to a dry-run
// before reaching here when the key is unset, so getResend() is only called on
// the live path.

import { Resend } from 'resend';

let _resend: Resend | null = null;

export function getResend(): Resend {
  if (_resend === null) {
    const key = process.env.RESEND_API_KEY;
    if (!key) {
      throw new Error('RESEND_API_KEY must be set to send email. See .env.example.');
    }
    _resend = new Resend(key);
  }
  return _resend;
}
