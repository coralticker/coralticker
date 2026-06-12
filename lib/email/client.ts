// The API key is read INSIDE getResend() at call time, NOT at module scope, so
// the module imports cleanly with RESEND_API_KEY unset (local dry-run / keyless
// build). The throw lands at send time, where a missing key is an actual error
// — but send.ts short-circuits to a dry-run before reaching here when the key is
// unset, so getResend() is only called on the live path.

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
