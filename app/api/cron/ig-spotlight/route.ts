// Vercel-cron -> GitHub workflow_dispatch relay for the Instagram spotlight
// publish-or-notify pipeline (CTK-159 Slice B). Mirrors the discord-digest
// relay: GH Actions schedule events fire hours late, so Vercel cron hits this
// route in-window and the route dispatches ig-spotlight.yml via the GitHub API.
// The Python selector + notify (scrapers/tools/ig_spotlight.py) is untouched --
// this is trigger relocation only.
//
// The cadence mode (`daily` | `weekly-roundup`) rides the cron path query
// string (vercel.json carries one entry per mode) and is forwarded as the
// workflow's `mode` input; window_hours (24 / 168) derives from mode inside
// ig_select.WINDOW_HOURS -- one source of truth for the mapping, and the weekly
// path is a real parameter, not a daily hard-code.
//
// Failure posture: one attempt, no retry loop. A non-204 from GitHub (or a
// thrown fetch) alerts the Slack operator channel and returns 500 so the
// failure is visible in the Vercel cron log too. The selector's window anchors
// at run time, so a missed fire self-heals at the next one.

export const dynamic = 'force-dynamic';

const DISPATCH_URL =
  'https://api.github.com/repos/coralticker/coralticker/actions/workflows/ig-spotlight.yml/dispatches';

const MODES = ['daily', 'weekly-roundup'] as const;
type Mode = (typeof MODES)[number];

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

  // Default to daily so a malformed/missing query param can't silently dispatch
  // the wrong window; reject anything not in the allowlist.
  const requested = new URL(request.url).searchParams.get('mode') ?? 'daily';
  if (!MODES.includes(requested as Mode)) {
    await alertSlack(`ig-spotlight dispatch skipped: unknown mode "${requested}"`);
    return new Response('bad mode', { status: 400 });
  }
  const mode = requested as Mode;

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
      body: JSON.stringify({ ref: 'main', inputs: { mode } }),
    });
    status = res.status;
  } catch (err) {
    await alertSlack(`ig-spotlight dispatch failed (${mode}): fetch threw (${err})`);
    return new Response('dispatch failed', { status: 500 });
  }

  if (status !== 204) {
    await alertSlack(
      `ig-spotlight dispatch failed (${mode}): GitHub API returned ${status} (expected 204)`,
    );
    return new Response('dispatch failed', { status: 500 });
  }

  return new Response(`dispatched ${mode}`, { status: 200 });
}
