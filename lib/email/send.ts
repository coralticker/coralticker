// Body-agnostic email transport. Carries ZERO row-format logic — transport
// neither knows nor cares what's in `html`.
//
// Failure posture: try/catch the Resend call; on failure console.error (Vercel
// function log) AND POST the operator Slack channel. The signup action IGNORES
// the {sent} return for control flow: the row is already written, capture is the
// contract, so a send failure never fails the signup. The return exists for
// callers that want to observe send state.
//
// Dry-run: with RESEND_API_KEY unset (local / CI), sendEmail logs the envelope
// and returns {sent:false} WITHOUT calling Resend or alerting — a keyless path
// is not a failure. Production always has the key in Vercel env, so keyless only
// happens off-prod where dry-run is the intent.

import { getResend } from './client.ts';
import { FROM } from './from.ts';

export interface SendEmailArgs {
  to: string;
  subject: string;
  html: string;
  headers?: Record<string, string>;
}

// Self-catching: an alert failure must not mask the send failure it is reporting.
async function alertSlack(text: string): Promise<void> {
  const webhook = process.env.SLACK_WEBHOOK_URL;
  if (!webhook) {
    console.error('SLACK_WEBHOOK_URL unset; alert not delivered:', text);
    return;
  }
  // Best-effort: an alert failure must not mask the send failure.
  await fetch(webhook, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  }).catch((err) => {
    console.error('Slack alert POST failed:', err);
  });
}

export async function sendEmail({
  to,
  subject,
  html,
  headers,
}: SendEmailArgs): Promise<{ sent: boolean }> {
  if (!process.env.RESEND_API_KEY) {
    if (process.env.VERCEL_ENV === 'production') {
      // Keyless in PRODUCTION is a misconfiguration, not a dry-run: every signup
      // would silently no-op on the Tier-1B trust surface (the form promises
      // "Check your email."). Surface it loudly — console.error + operator-
      // channel alert — but still return {sent:false} without throwing, to
      // preserve the best-effort contract (the signup row is already written).
      console.error(
        `RESEND_API_KEY unset in production — confirm email NOT sent: to=${to} subject=${JSON.stringify(subject)}`,
      );
      await alertSlack(
        `RESEND_API_KEY unset in production — confirm email not sent (to=${to}). Check Vercel env.`,
      );
      return { sent: false };
    }
    // Off-prod dry-run (keyless). Log the envelope only — never the html body,
    // which carries the confirm/unsubscribe token. Not a failure: no alert.
    console.info(
      `[email dry-run] RESEND_API_KEY unset — would send to=${to} subject=${JSON.stringify(subject)}`,
    );
    return { sent: false };
  }

  try {
    const { error } = await getResend().emails.send({
      from: FROM,
      to,
      subject,
      html,
      headers,
    });
    // Resend returns API errors in-band (does not throw); funnel into the catch
    // so the success path is the single source of {sent:true}.
    if (error) {
      throw new Error(`Resend API error: ${error.name}: ${error.message}`);
    }
    return { sent: true };
  } catch (err) {
    console.error(
      `sendEmail failed: to=${to} subject=${JSON.stringify(subject)}`,
      err,
    );
    await alertSlack(
      `email send failed: to=${to} subject=${JSON.stringify(subject)} (${String(err)})`,
    );
    return { sent: false };
  }
}
