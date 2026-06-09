// /unsubscribe?t=<token> — CTK-016 Leg 4.
//
// GET/POST split (plan §Leg 4) to survive prefetch bots — Gmail's image proxy,
// Apple Mail Privacy Protection, and link scanners GET-prefetch every link in a
// message. A GET that wrote unsubscribed_at would silently unsubscribe people
// whose client merely previewed the email. So:
//
//   GET  ?t=<token>  -> render the confirm-button page. NO DB write.
//   POST (t in query or body) -> set unsubscribed_at, serve the done page.
//
// One URL serves both because RFC 8058 List-Unsubscribe one-click (CTK-136's
// digest footer header) POSTs `List-Unsubscribe=One-Click` to the SAME https
// URL the List-Unsubscribe header carries — with the token in the ?t= query.
// Reading the token query-first covers both the one-click bot and the human
// button (whose form action preserves ?t=).
//
// These are email-utility surfaces: hand-rendered HTML, not React pages under
// app/layout. A page.tsx can't accept POST, and the one-click POST must hit this
// exact URL — so a route handler owns both verbs. Copy is /signup/confirmed-
// class, ratified by Jon 2026-06-09 (plan §Leg 4). Brand fonts fall back to
// system stacks here (no @font-face); flagged for /brand-manager review.

import { getNeonSql } from '@/lib/db/neon';

export const dynamic = 'force-dynamic';

const INK = '#1A1A1A';
const FOREST = '#1B5E20';
const SANS =
  "'IBM Plex Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif";

// The `t` value is attacker-controllable (reflected from the URL), so escape it
// before it ever touches the HTML. Legit tokens (base64url / uuid) are inert,
// but a crafted ?t= must not break out into markup.
function htmlEscape(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function utilityPage(heading: string, bodyHtml: string): string {
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>${heading}</title>
</head>
<body style="margin:0;padding:0;background:#FFFFFF;font-family:${SANS};color:${INK};">
  <main style="max-width:640px;margin:0 auto;padding:48px 24px;">
    <div style="font-size:22px;line-height:1;margin-bottom:36px;">
      <span style="font-weight:700;">coral</span><span style="font-weight:400;">ticker</span><span style="font-weight:700;color:${FOREST};">.</span>
    </div>
    <h1 style="font-size:30px;line-height:1.2;font-weight:700;margin:0 0 16px;">${heading}</h1>
    ${bodyHtml}
  </main>
</body>
</html>`;
}

function htmlResponse(body: string, status = 200): Response {
  return new Response(body, {
    status,
    headers: { 'content-type': 'text/html; charset=utf-8' },
  });
}

// GET — render the confirm-button page. No DB write (prefetch-bot safety).
export async function GET(request: Request): Promise<Response> {
  const token = new URL(request.url).searchParams.get('t');
  if (!token) {
    return htmlResponse(
      utilityPage('Unsubscribe?', '<p style="font-size:16px;line-height:1.5;">This link is missing its token.</p>'),
      400,
    );
  }

  const safe = htmlEscape(token);
  // The button POSTs to this same URL with ?t= preserved; a hidden field is a
  // belt-and-suspenders fallback for any proxy that drops the action query.
  const body = `
    <p style="font-size:16px;line-height:1.5;margin:0 0 28px;">Click below to stop the weekly digest.</p>
    <form method="POST" action="/unsubscribe?t=${encodeURIComponent(token)}">
      <input type="hidden" name="token" value="${safe}">
      <button type="submit" style="display:inline-block;font-family:${SANS};font-size:16px;font-weight:700;line-height:1;color:#FFFFFF;background:${FOREST};border:0;border-radius:6px;padding:14px 28px;cursor:pointer;">Unsubscribe</button>
    </form>`;
  return htmlResponse(utilityPage('Unsubscribe?', body));
}

// POST — set unsubscribed_at, serve the done page. Handles both the human button
// (token in query, hidden field fallback) and the RFC 8058 one-click bot (token
// in query, body = `List-Unsubscribe=One-Click`).
export async function POST(request: Request): Promise<Response> {
  let token = new URL(request.url).searchParams.get('t');
  if (!token) {
    // Fall back to the form body (human button without a query-bearing action).
    try {
      const form = await request.formData();
      const fromBody = form.get('token');
      if (typeof fromBody === 'string') token = fromBody;
    } catch {
      // Non-form body (or none) — token stays null; handled below.
    }
  }

  if (!token) {
    return htmlResponse(
      utilityPage('Unsubscribe?', '<p style="font-size:16px;line-height:1.5;">This request is missing its token.</p>'),
      400,
    );
  }

  try {
    const sql = getNeonSql();
    // Idempotent: gate on NULL so a repeat unsubscribe (or one-click after a
    // human unsub) is a no-op but still serves the done page; first-unsub
    // timestamp stays frozen.
    await sql`
      UPDATE email_signups
      SET unsubscribed_at = now()
      WHERE token = ${token} AND unsubscribed_at IS NULL
    `;
  } catch (err) {
    // Best-effort posture: log, but still serve the done page rather than show
    // a failure on a trust surface. A re-submit retries the write.
    console.error('unsubscribe: unsubscribed_at UPDATE failed', err);
  }

  const body =
    '<p style="font-size:16px;line-height:1.5;margin:0;">I won&#39;t send the digest anymore.</p>';
  return htmlResponse(utilityPage('Unsubscribed.', body));
}
