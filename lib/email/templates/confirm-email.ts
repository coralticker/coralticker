// The double-opt-in confirm email body — a pure body-builder carrying NO
// transport concern and NO row-format logic (this email is transactional and
// INV-01-exempt).
//
// Copy rationale:
//   - H1            "Confirm your email."  (NOT "You're subscribed." — false
//                   until the click sets confirmed_at)
//   - Single CTA -> confirmUrl(token). NO /new link, NO unsubscribe link: any
//                   non-confirm click is a confirm-rate leak, and there is no
//                   active subscription to unsubscribe from pre-click.
//   - Footer       "Didn't sign up? Ignore this — you won't hear from me again."
//                   (true ONLY because v1 sends no confirm-reminder nudge.)
// Transactional => no List-Unsubscribe header (set by the caller, not here).
//
// VISUAL: the brand hero lockup hand-translated into email-safe HTML — table
// layout + inline styles, no Tailwind/external CSS (email clients can't use
// them). The React component is deliberately NOT imported. Brand tokens:
//   - wordmark   "coral" 700 + "ticker" 400 + "." forest #1B5E20 700, on ink
//                #1A1A1A, IBM Plex Sans (web-safe sans fallback in inboxes)
//   - rule       1px ink em-dash motif, spanning the lockup width
//   - tagline    "Never miss the drop." IBM Plex Mono, 700, uppercase, 0.08em
//                tracking, ink — wordmark 1.60× tagline

import { confirmUrl } from '../token.ts';

const INK = '#1A1A1A';
const FOREST = '#1B5E20';
const PAGE_BG = '#FFFFFF';

// IBM Plex Sans / Mono aren't installed in inboxes; degrade to the closest
// system stacks rather than ship a broken @font-face that most clients strip.
const SANS =
  "'IBM Plex Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif";
const MONO = "'IBM Plex Mono', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace";

// Wordmark 1.60× tagline (wordmark-dominant lock). Scaled down from the site
// hero (38/24) for inbox comfort; ratio preserved.
const WORDMARK_PX = 32;
const TAGLINE_PX = 20;

const SUBJECT = 'Confirm your email.';

// Content is H1 + CTA + footer only — no supporting body line: the spare
// H1 -> button reads on-voice and a connective line would be unratified copy on
// a Tier-1B trust surface.
const FOOTER_LINE = "Didn't sign up? Ignore this — you won't hear from me again.";

export function confirmEmail(token: string): { subject: string; html: string } {
  const href = confirmUrl(token);

  // The hero lockup as a 3-cell table row (wordmark | spanning rule | tagline),
  // valign="middle" — the rule + tagline vertically center against the wordmark.
  // The centered version reads cleaner in-inbox than a baseline-aligned/rule-lift
  // translation, which fought email clients' inconsistent vertical metrics. The
  // rule cell is width:100% so it absorbs slack first (the flex-auto analogue).
  const lockup = `
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;">
      <tr>
        <td valign="middle" style="white-space:nowrap;font-family:${SANS};font-size:${WORDMARK_PX}px;line-height:1;color:${INK};">
          <span style="font-weight:700;">coral</span><span style="font-weight:400;">ticker</span><span style="font-weight:700;color:${FOREST};">.</span>
        </td>
        <td valign="middle" width="100%" style="padding:0 14px;">
          <div style="height:1px;background:${INK};line-height:1px;font-size:0;">&nbsp;</div>
        </td>
        <td valign="middle" style="white-space:nowrap;font-family:${MONO};font-size:${TAGLINE_PX}px;line-height:1;font-weight:700;text-transform:uppercase;letter-spacing:0.08em;color:${INK};">
          Never miss the drop.
        </td>
      </tr>
    </table>`;

  const html = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light">
  <title>${SUBJECT}</title>
</head>
<body style="margin:0;padding:0;background:${PAGE_BG};">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;background:${PAGE_BG};">
    <tr>
      <td align="center" style="padding:40px 20px;">
        <table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;width:600px;max-width:100%;">
          <tr>
            <td style="padding-bottom:36px;">
              ${lockup}
            </td>
          </tr>
          <tr>
            <td style="font-family:${SANS};font-size:24px;line-height:1.3;font-weight:700;color:${INK};padding-bottom:28px;">
              Confirm your email.
            </td>
          </tr>
          <tr>
            <td style="padding-bottom:40px;">
              <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;">
                <tr>
                  <td align="center" bgcolor="${INK}" style="border-radius:6px;">
                    <a href="${href}" style="display:inline-block;font-family:${SANS};font-size:16px;font-weight:700;line-height:1;color:#FFFFFF;text-decoration:none;padding:14px 28px;border-radius:6px;background:${INK};">
                      Confirm email
                    </a>
                  </td>
                </tr>
              </table>
            </td>
          </tr>
          <tr>
            <td style="font-family:${SANS};font-size:13px;line-height:1.5;color:${INK};opacity:0.6;border-top:1px solid #EAE6E0;padding-top:20px;">
              ${FOOTER_LINE}
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>`;

  return { subject: SUBJECT, html };
}
