// app/api/cron/email-digest/route.ts
//
// CTK-136 — daily email digest cron. Unlike the CTK-011 Discord digest (a
// Vercel-cron -> GitHub workflow_dispatch RELAY, kept only because it predates
// Vercel cron and had a legacy GH Actions script), email has no legacy script,
// so this route does the work IN-ROUTE: query -> render -> send, via
// runEmailDigest() in lib/email/digest.ts. No GH-Actions indirection.
//
// It mirrors the discord-digest route's POSTURE, not its mechanism:
//   - export const dynamic = 'force-dynamic'
//   - CRON_SECRET Bearer auth, fail-closed on an unset secret (without the
//     guard an unset secret would accept the literal header "Bearer undefined")
//   - any failure (query throw, render throw, prod-keyless, Resend error) ->
//     alert the Slack operator channel (decision #39 operator/user split) AND
//     return 500, so the failure is visible in the Vercel cron log too. A
//     best-effort alert must not mask the underlying failure.
//
// The digest's 24h lookback anchors at run time, so a missed day self-heals at
// the next fire — same posture as the Discord digest.

import { runEmailDigest } from '@/lib/email/digest';

export const dynamic = 'force-dynamic';

// COPIED verbatim from app/api/cron/discord-digest/route.ts (the same Tier-3
// shared-helper extraction lib/email/send.ts defers — this is the third copy,
// consistent with that deferral). Self-catching: an alert failure must not mask
// the digest failure it is reporting.
async function alertSlack(text: string): Promise<void> {
  const webhook = process.env.SLACK_WEBHOOK_URL;
  if (!webhook) {
    console.error('SLACK_WEBHOOK_URL unset; alert not delivered:', text);
    return;
  }
  await fetch(webhook, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  }).catch((err) => {
    console.error('Slack alert POST failed:', err);
  });
}

export async function GET(request: Request) {
  const secret = process.env.CRON_SECRET;
  // Fail closed on missing config — without this guard, an unset secret would
  // accept the literal header "Bearer undefined".
  if (!secret || request.headers.get('authorization') !== `Bearer ${secret}`) {
    return new Response('Unauthorized', { status: 401 });
  }

  try {
    const result = await runEmailDigest(new Date());
    return Response.json(result, { status: 200 });
  } catch (err) {
    await alertSlack(`email-digest failed: ${String(err)}`);
    return new Response('digest failed', { status: 500 });
  }
}
