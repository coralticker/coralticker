// Vercel-cron -> GitHub workflow_dispatch relay for the daily Discord digest:
// GH Actions schedule events are best-effort and fired hours late, so Vercel
// cron hits this route in-window and the route dispatches the existing
// discord-digest.yml workflow via the GitHub API. The digest script itself is
// untouched -- this is trigger relocation only.
//
// Failure posture: one attempt, no retry loop. A non-204 from GitHub (or a
// thrown fetch) alerts the Slack operator channel and returns 500 so the failure
// is visible in the Vercel cron log too. The digest's 24h lookback anchors at
// run time, so a missed day self-heals at the next fire.

export const dynamic = 'force-dynamic';

const DISPATCH_URL =
  'https://api.github.com/repos/coralticker/coralticker/actions/workflows/discord-digest.yml/dispatches';

async function alertSlack(text: string): Promise<void> {
  const webhook = process.env.SLACK_WEBHOOK_URL;
  if (!webhook) {
    console.error('SLACK_WEBHOOK_URL unset; alert not delivered:', text);
    return;
  }
  // Best-effort: an alert failure must not mask the dispatch failure.
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
  // Fail closed on missing config -- without this guard, an unset secret
  // would accept the literal header "Bearer undefined".
  if (!secret || request.headers.get('authorization') !== `Bearer ${secret}`) {
    return new Response('Unauthorized', { status: 401 });
  }

  let status: number;
  try {
    const res = await fetch(DISPATCH_URL, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${process.env.GH_DISPATCH_TOKEN}`,
        Accept: 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
        'User-Agent': 'coralticker-cron',
      },
      body: JSON.stringify({ ref: 'main' }),
    });
    status = res.status;
  } catch (err) {
    await alertSlack(`discord-digest dispatch failed: fetch threw (${err})`);
    return new Response('dispatch failed', { status: 500 });
  }

  if (status !== 204) {
    await alertSlack(
      `discord-digest dispatch failed: GitHub API returned ${status} (expected 204)`,
    );
    return new Response('dispatch failed', { status: 500 });
  }

  return new Response('dispatched', { status: 200 });
}
