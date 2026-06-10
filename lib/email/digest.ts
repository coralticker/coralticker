// lib/email/digest.ts
//
// CTK-136 — v1 email daily digest. The in-route query -> render -> send body
// for app/api/cron/email-digest/route.ts. No GH-Actions relay (email has no
// legacy script, unlike the CTK-011 Discord digest this is adapted from).
//
// Source: get_listing_lead_event(NULL, 24, NULL, NULL) — migration 0030,
// fleet-wide 24h window, one row per listing, lead event only. Lead-event
// precedence (price-dropped > back-in-stock > just-listed) is inherited from
// the RPC's ranking; nothing here re-derives it (Q-1 lean: reuse as-is for
// INV-01 parity with the Discord digest). OOS rows never arrive: all three RPC
// arms filter in_stock = true (deal-buyer canon, branding-guide.md §"State
// markers" — the OOS adapter shape is cited in plan.md if a variant ever
// renders one).
//
// INV-01 channel parity: each listing line renders through formatDataRow()
// (lib/format/data-row.ts) — same field order, same labels, same em-dash
// separator as the web <DataRow> and the Discord embed. This file is the HTML
// channel-adapter on top: <strong> on the coral name, semantic <del> on the
// was-value and bold-forest on the now-value of price-drop-new / vendor-markdown
// fields (decision #75, mirroring components/ui/data-row.tsx RenderValue),
// applied at field construction so the canonical shape still flows through the
// shared primitive.
//
// HAND-PORT (CTK-123 soft dependency): the field-derivation logic — the Price
// precedence chain (price-drop-new > vendor-markdown at >=5% epsilon-guarded >
// bare) and the 'price on request' null-price (auction) shape — is hand-ported
// from scripts/discord-digest.ts:buildFields(), itself a port of
// components/ui/data-row.tsx. This is a KNOWING interim duplicate (two copies of
// the precedence chain), the same one the Discord script carries. When CTK-123
// lands the shared lib/format/ buildFields(), this adapter re-points to it; the
// first-ship side-by-side smoke (INV-01 check-cadence 2) is the backstop until
// then. See plan.md Risks.
//
// SCAFFOLD (landed CTK-136, co-signed against CTK-136/email-scaffold-spec.md):
// wrapDigestDoc() below is the real branded HTML email document — table layout
// for mail-client compat, a wordmark-alone masthead (spec §3 weigh-in resolved
// 2026-06-09: tagline dropped on the daily surface per Jon + /reef-lead), a 600px
// centered column, styled vendor-group headers + listing lines (§4), and the
// CAN-SPAM-complete, product-voice footer (§5). Brand tokens (INK, FOREST,
// PAGE_BG, the SANS stack, wordmark sizing) mirror lib/email/templates/
// confirm-email.ts so the two emails read as one brand. The FIELD-LEVEL render
// (buildFields/buildLine — the `**name** — Price. … — Listed. …` content) is
// INV-01-locked and untouched; the scaffold owns only the surrounding chrome
// (document, masthead, header/line styling, footer). Both Jon weigh-ins are now
// resolved: PAGE_BG = white (§6) and wordmark-alone masthead (§3).
//
// Testability: the pure builders (buildFields, buildLine, groupByVendor,
// buildListingsHtml, buildFooter, listUnsubscribeHeaders, buildSubject,
// wrapDigestDoc) import clean with no env. The DB fetches and the Resend send
// use a dynamic import for lib/db/neon.ts (module-scope env throw) and call-time
// getResend(), so they never run under `node --test`. Mirrors the Discord
// script's dynamic-import-for-db pattern.

import { formatDataRow } from '../format/data-row.ts';
import type { DataRowField } from '@/components/ui/data-row';
import { unsubscribeUrl } from './token.ts';
import { FROM } from './from.ts';

export interface DigestRow {
  id: number;
  raw_title: string;
  current_price: number | string | null;
  compare_at_price: number | string | null;
  prior_price: number | string | null;
  event: 'price-dropped' | 'back-in-stock' | 'just-listed';
  event_at: string;
  first_seen_at: string;
  vendor_display_name: string;
  // The vendor's product page (the buy link). Already returned by
  // get_listing_lead_event (migration 0030); the coral name links to it. Nullable
  // — a row without a URL renders the name unlinked (graceful fallback).
  product_url: string | null;
}

export interface Recipient {
  email: string;
  token: string;
}

// Resend batch endpoint caps at 100 messages per call.
const BATCH_SIZE = 100;

// Brand tokens, mirrored verbatim from lib/email/templates/confirm-email.ts (the
// Jon-ratified 2026-06-09 precedent) so the two emails render as one brand.
// FOREST stays the field-level now-value accent (decision #75); the rest are the
// scaffold's masthead + chrome tokens.
const INK = '#1A1A1A';
const FOREST = '#1B5E20';
// branding-guide §"Served-neutral re-spec": #E5E7EB is the single hairline /
// under-rule / border tone (the vendor-header rule + footer top-border).
const LINE = '#E5E7EB';
// confirm-email shipped white; §"Color system" canon is cream #F5F1EA. Built to
// the spec §6 lean (white — cross-email consistency + inbox-render reliability);
// OPEN Jon weigh-in (guide-amendment class — do not silently lock cream here).
const PAGE_BG = '#FFFFFF';

// IBM Plex Sans isn't installed in inboxes; degrade to the closest system stack
// rather than ship a stripped @font-face (verbatim from confirm-email.ts).
const SANS =
  "'IBM Plex Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif";

const WORDMARK_PX = 32;

// MASTHEAD — wordmark alone, no tagline. The daily digest is a utility, not a
// welcome moment: a slogan seen every morning goes to wallpaper and drifts toward
// the hype register the brand avoids, so the nameplate carries the brand presence
// and the tagline is dropped here (Jon + /reef-lead, 2026-06-09 — exercising the
// spec §3 wordmark-alone weigh-in; supersedes the confirm-email full-lockup reuse
// on THIS surface only; the confirm email keeps its tagline as a first-impression
// asset). /brand-manager folds spec §3 to match. Left-aligned, same WORDMARK_PX as
// the confirm email so the nameplate is pixel-identical across both emails.
// The wordmark links home (newspaper-masthead pattern — the nameplate IS the site
// link). NOT underlined: it's the brand mark, not a text link; the L"links are
// underlined" rule is for in-copy text links, and underlining the wordmark would
// fight the colored-full-stop mark. color:INK keeps it from turning link-blue; the
// forest dot's inner span overrides.
const SITE_URL = 'https://coralticker.com';
const MASTHEAD = `<div style="font-family:${SANS};font-size:${WORDMARK_PX}px;line-height:1;color:${INK};">` +
  `<a href="${SITE_URL}" style="color:${INK};text-decoration:none;">` +
  `<span style="font-weight:700;">coral</span><span style="font-weight:400;">ticker</span><span style="font-weight:700;color:${FOREST};">.</span>` +
  `</a>` +
  `</div>`;

// CAN-SPAM requires a physical postal address on every commercial send. Jon's
// registered mailbox, landed 2026-06-09 — the first-ship CAN-SPAM gate clears.
const POSTAL_ADDRESS = 'PO Box 115, 221 Najoles Road, Millersville, MD 21108';

// RPC precedence ranks, mirrored for within-vendor display order only — the
// lead-event CHOICE per listing already happened in the RPC.
const PRECEDENCE: Record<DigestRow['event'], number> = {
  'price-dropped': 1,
  'back-in-stock': 2,
  'just-listed': 3,
};

// Escape HTML metacharacters in vendor-controlled text (coral names, vendor
// names) before it touches markup. Mirrors app/unsubscribe/route.ts:htmlEscape.
// The styling tags this module adds are trusted; the data values are not.
export function htmlEscape(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// Verbatim port of scripts/discord-digest.ts:formatPrice — null price is the
// auction parse-time shape ('price on request', never a fake buy price per
// project canon). Neon's HTTP driver returns numerics as strings. Output is
// purely numeric/literal, so it carries no HTML-unsafe characters.
function formatPrice(value: number | string | null): string {
  if (value === null) return 'price on request';
  return `$${Number(value).toFixed(2)}`;
}

function asNumber(value: number | string | null): number | null {
  return value === null ? null : Number(value);
}

// Mirrors scripts/discord-digest.ts:buildFields() Price precedence chain:
// price-drop-new > vendor-markdown (>=5% epsilon-guarded) > bare. The OOS
// 'invalidated' branch is intentionally absent — the RPC filters in_stock =
// true on all arms, so no OOS row can reach this adapter. HTML styling (semantic
// <del> on the was-value, bold-forest <strong> on the now-value) lands here at
// field construction; formatValue()'s channel-neutral adjacency shape (struck
// old + new, no connective words — card-parity, 2026-06-09) then carries it
// through the shared primitive.
export function buildFields(row: DigestRow): DataRowField[] {
  const fields: DataRowField[] = [];
  const currentPrice = asNumber(row.current_price);
  const compareAtPrice = asNumber(row.compare_at_price);
  const priorPrice = asNumber(row.prior_price);

  if (priorPrice !== null && currentPrice !== null) {
    fields.push({
      label: 'Price',
      value: {
        kind: 'price-drop-new',
        oldValue: `<del>${formatPrice(priorPrice)}</del>`,
        newValue: `<strong style="color:${FOREST};font-weight:700;">${formatPrice(currentPrice)}</strong>`,
      },
    });
  } else if (
    compareAtPrice !== null &&
    currentPrice !== null &&
    // Subtract-then-compare with epsilon per discord-digest.ts / data-row.tsx
    // (IEEE754 misses ~29% of clean integer-dollar 5% markdowns otherwise).
    compareAtPrice - currentPrice >= currentPrice * 0.05 - 1e-9
  ) {
    fields.push({
      label: 'Price',
      value: {
        kind: 'vendor-markdown',
        oldValue: `<del>${formatPrice(compareAtPrice)}</del>`,
        newValue: `<strong style="color:${FOREST};font-weight:700;">${formatPrice(currentPrice)}</strong>`,
      },
    });
  } else {
    fields.push({ label: 'Price', value: formatPrice(currentPrice) });
  }

  // Mirrors discord-digest.ts 'Listed'/'Back' field (event_at ?? first_seen_at).
  // back-in-stock rows get the 'Back' label so the restock reads on the line
  // without a lead sentence — /brand-manager-ratified 2026-06-06 on lead-less
  // channel compositions.
  fields.push({
    label: row.event === 'back-in-stock' ? 'Back' : 'Listed',
    value: {
      kind: 'relative-time',
      timestamp: row.event_at ?? row.first_seen_at,
    },
  });

  return fields;
}

// One listing line: the bold coral name links to the vendor's product page (the
// buy link — new tab, neutral ink + underline per branding-guide §"Color system"
// link rule), em-dash, then the formatDataRow() render. raw_title + product_url
// are vendor-controlled, so both are HTML-escaped; the <strong>/<a> are ours. A
// null product_url renders the name unlinked (graceful fallback). Same destination
// as the web feed (listing-row-frame.tsx — whole card -> product_url, new tab).
export function buildLine(row: DigestRow, now: Date): string {
  const name = `<strong>${htmlEscape(row.raw_title)}</strong>`;
  // https-only on the vendor-controlled URL (CTK-136 /code-review F3): htmlEscape
  // already closes the attribute-breakout, and the scheme allowlist drops
  // javascript:/data: schemes — a non-https product_url renders the name unlinked.
  const named =
    row.product_url && /^https:\/\//i.test(row.product_url)
      ? `<a href="${htmlEscape(row.product_url)}" target="_blank" rel="noopener noreferrer" style="color:${INK};text-decoration:underline;">${name}</a>`
      : name;
  return `${named} — ${formatDataRow(buildFields(row), now)}`;
}

interface VendorGroup {
  vendor: string;
  rows: DigestRow[];
}

// Verbatim port of discord-digest.ts:groupByVendor — vendors busiest-first
// (count desc, name asc tiebreak); within a vendor, precedence rank then
// newest-first.
export function groupByVendor(rows: DigestRow[]): VendorGroup[] {
  const byVendor = new Map<string, DigestRow[]>();
  for (const row of rows) {
    const group = byVendor.get(row.vendor_display_name);
    if (group) {
      group.push(row);
    } else {
      byVendor.set(row.vendor_display_name, [row]);
    }
  }
  const groups: VendorGroup[] = [...byVendor.entries()].map(([vendor, vendorRows]) => ({
    vendor,
    rows: vendorRows.sort(
      (a, b) =>
        PRECEDENCE[a.event] - PRECEDENCE[b.event] ||
        Date.parse(b.event_at) - Date.parse(a.event_at),
    ),
  }));
  return groups.sort(
    (a, b) => b.rows.length - a.rows.length || a.vendor.localeCompare(b.vendor),
  );
}

// The listings content block — the recipient-INDEPENDENT body, rendered once.
// Unlike the Discord embed (4096-char cap, N=3 per-vendor cap), email has no
// length ceiling, so every line renders: vendor header + one line per listing.
// Chrome styling per spec §4: the vendor <h2> is a content section header
// (sentence-case SANS, bold vendor name + regular-weight `— N drops` count, ink,
// 1px #E5E7EB under-rule) — NOT mono-uppercase chrome. The listing <p> lines are
// SANS/ink; the field-level brand render (bold name, em-dash, struck/forest
// prices) flows untouched through buildLine() -> formatDataRow() per INV-01.
// Inline styles only — email clients strip <head><style>. Values render SANS
// (not MONO): formatDataRow() emits one channel-neutral string and re-segmenting
// it to inject MONO would re-format, violating the wrap-don't-reformat lock
// (INV-01) — flagged to /brand-manager at co-sign.
export function buildListingsHtml(rows: DigestRow[], now: Date): string {
  const groups = groupByVendor(rows);
  return groups
    .map((group) => {
      const n = group.rows.length;
      const header =
        `<h2 style="margin:0 0 12px;padding:0 0 8px;border-bottom:1px solid ${LINE};` +
        `font-family:${SANS};font-size:18px;line-height:1.3;font-weight:400;color:${INK};">` +
        `<span style="font-weight:700;">${htmlEscape(group.vendor)}</span> — ${n} drop${n === 1 ? '' : 's'}` +
        `</h2>`;
      const lines = group.rows
        .map(
          (row) =>
            `<p style="margin:0 0 10px;font-family:${SANS};font-size:15px;line-height:1.5;color:${INK};">${buildLine(row, now)}</p>`,
        )
        .join('\n');
      return `<div style="margin-bottom:28px;">${header}\n${lines}</div>`;
    })
    .join('\n');
}

// CAN-SPAM footer (spec §5): product-voice, FULL-INK (not de-emphasized — the
// CTK-129 sweep retired the low-emphasis register and legally-required text must
// stay legible). Subjectless "why you're getting this" sentence (no "I"/"Jon"/
// "we" — branding-guide §"Surface boundary" names email digests in the no-`I`
// list; §1), the working per-recipient one-click unsubscribe link (the ONLY
// per-recipient element, Q-5 shape), the physical postal address (CAN-SPAM,
// landed 2026-06-09), and the standing "Not affiliated with vendors." disclaimer.
// `Last scrape: {timestamp}` is dropped — the subject date + per-line relative
// times already carry freshness. Links render neutral ink + underline per
// §"Color system" (color carries no affordance). The Hunter-waitlist CTA slot is
// reserved but ships no copy at v1 (no public paid-tier name, no destination).
export function buildFooter(token: string): string {
  const base = `font-family:${SANS};font-size:13px;line-height:1.6;color:${INK};`;
  return (
    `<div style="border-top:1px solid ${LINE};margin-top:8px;padding-top:24px;${base}">` +
    `<p style="margin:0 0 12px;${base}">You confirmed your email for daily coral drops at coralticker.com.</p>` +
    `<p style="margin:0 0 12px;${base}"><a href="${unsubscribeUrl(token)}" style="color:${INK};text-decoration:underline;">Unsubscribe.</a></p>` +
    `<p style="margin:0 0 12px;${base}">${POSTAL_ADDRESS}</p>` +
    `<!-- Hunter-waitlist CTA slot reserved (CTK-136 plan objective); no copy at v1 — no public paid-tier name (branding-guide §L120) and no waitlist destination built yet. -->` +
    `<p style="margin:0;${base}">Not affiliated with vendors.</p>` +
    `</div>`
  );
}

// RFC 8058 bulk-sender one-click headers (Q-4, locked). List-Unsubscribe carries
// the per-recipient https target in angle brackets; List-Unsubscribe-Post opts
// the message into one-click. The token rides in the ?t= query because
// app/unsubscribe/route.ts:POST reads ?t= FIRST — the one-click bot POSTs
// `List-Unsubscribe=One-Click` to this exact URL.
export function listUnsubscribeHeaders(token: string): Record<string, string> {
  return {
    'List-Unsubscribe': `<${unsubscribeUrl(token)}>`,
    'List-Unsubscribe-Post': 'List-Unsubscribe=One-Click',
  };
}

// ET-anchored subject date, mirroring discord-digest.ts:buildTitle (/code-review
// #9 fold): a late fire near the UTC day boundary must not date-skip. en-CA
// renders ISO-shaped YYYY-MM-DD.
export function buildSubject(now: Date): string {
  const date = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'America/New_York',
  }).format(now);
  return `CoralTicker — daily drops ${date}`;
}

// The branded digest document (spec §3-§6): white body, a centered 600px column
// holding the hero-lockup masthead, the listings body (rendered once), and the
// per-recipient CAN-SPAM footer. Table layout + inline styles only — the only
// shape email clients render reliably. Mirrors confirm-email.ts's outer/inner
// table structure verbatim so the two emails share one frame.
export function wrapDigestDoc(listingsHtml: string, footerHtml: string, subject: string): string {
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light">
  <title>${htmlEscape(subject)}</title>
</head>
<body style="margin:0;padding:0;background:${PAGE_BG};">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;background:${PAGE_BG};">
    <tr>
      <td align="center" style="padding:40px 20px;">
        <table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;width:600px;max-width:100%;">
          <tr>
            <td style="padding-bottom:36px;">
              ${MASTHEAD}
            </td>
          </tr>
          <tr>
            <td>
              ${listingsHtml}
            </td>
          </tr>
          <tr>
            <td>
              ${footerHtml}
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>`;
}

// --- Live path (DB + Resend). Dynamic import for neon keeps its module-scope
// env throw out of test runs; getResend() is call-time, so importing this file
// is env-clean. None of the below runs under `node --test`. ---

async function fetchRows(): Promise<DigestRow[]> {
  const { getNeonSql } = await import('../db/neon.ts');
  const sql = getNeonSql();
  const rows = await sql`
    SELECT id, raw_title, current_price, compare_at_price, prior_price,
           event, event_at, first_seen_at, vendor_display_name, product_url
    FROM get_listing_lead_event(NULL, 24, NULL, NULL)
  `;
  return rows as unknown as DigestRow[];
}

async function fetchRecipients(): Promise<Recipient[]> {
  const { getNeonSql } = await import('../db/neon.ts');
  const sql = getNeonSql();
  // The token projection is load-bearing: the footer link is
  // unsubscribeUrl(token) and the one-click route gates on WHERE token = ${...}.
  // A SELECT that omits token ships dead unsubscribe links on every message.
  const rows = await sql`
    SELECT email, token
    FROM email_signups
    WHERE confirmed_at IS NOT NULL AND unsubscribed_at IS NULL
  `;
  return rows as unknown as Recipient[];
}

function chunk<T>(items: T[], size: number): T[][] {
  const out: T[][] = [];
  for (let i = 0; i < items.length; i += size) {
    out.push(items.slice(i, i + size));
  }
  return out;
}

export interface DigestResult {
  status: 'sent' | 'no-events' | 'no-recipients' | 'dry-run';
  rows: number;
  recipients: number;
  sent: number;
}

// Orchestrator the cron route calls inside its try/catch. Throws on any send
// failure (prod-keyless, Resend in-band error) so the route alerts the operator
// channel and returns 500 — loud failure, no silent partial send. The 0-event
// and 0-recipient no-ops return normally (route -> 200), mirroring the Discord
// digest's 0-row skip.
export async function runEmailDigest(now: Date): Promise<DigestResult> {
  const rows = await fetchRows();
  if (rows.length === 0) {
    // Near-impossible across 11 hourly-scraped vendors; if it happens, skip
    // rather than broadcast an empty digest.
    console.log('email-digest: 0 lead events in the 24h window; not sending');
    return { status: 'no-events', rows: 0, recipients: 0, sent: 0 };
  }

  const recipients = await fetchRecipients();
  if (recipients.length === 0) {
    console.log('email-digest: 0 confirmed recipients; not sending');
    return { status: 'no-recipients', rows: rows.length, recipients: 0, sent: 0 };
  }

  // Render the listings body ONCE (recipient-independent). The footer
  // unsubscribe link is the only per-recipient element (Q-5 shape).
  const listingsHtml = buildListingsHtml(rows, now);
  const subject = buildSubject(now);

  // Keyless dry-run guard, mirroring lib/email/send.ts. Off-prod with no key:
  // log the envelope summary and return without sending (not a failure). In
  // production a missing key is a misconfiguration — throw so the route alerts
  // loudly and returns 500 (the digest has no "row already written" best-effort
  // contract to preserve, unlike the signup path).
  if (!process.env.RESEND_API_KEY) {
    if (process.env.VERCEL_ENV === 'production') {
      throw new Error(
        `RESEND_API_KEY unset in production — daily digest NOT sent to ${recipients.length} recipients`,
      );
    }
    console.info(
      `[email-digest dry-run] RESEND_API_KEY unset — would send subject=${JSON.stringify(subject)} to ${recipients.length} recipients (${rows.length} listings)`,
    );
    return { status: 'dry-run', rows: rows.length, recipients: recipients.length, sent: 0 };
  }

  // Live send. Resend's batch endpoint takes an array of distinct messages and
  // (resend 6.12.4) carries per-message headers — so the per-recipient footer
  // and per-recipient List-Unsubscribe header both ride one request per 100.
  // Q-5: this uses getResend().batch.send directly rather than looping
  // sendEmail(); the alternative (loop the single-message sendEmail wrapper) is
  // surfaced for /lead-backend. Either way the body is rendered once above.
  const { getResend } = await import('./client.ts');
  const resend = getResend();

  let sent = 0;
  for (const batch of chunk(recipients, BATCH_SIZE)) {
    const messages = batch.map((r) => ({
      from: FROM,
      to: r.email,
      subject,
      html: wrapDigestDoc(listingsHtml, buildFooter(r.token), subject),
      headers: listUnsubscribeHeaders(r.token),
    }));
    // Resend returns API errors in-band (does not throw); funnel to a throw so
    // the route's catch alerts + 500s — no single-batch failure is silently
    // swallowed. Across MULTIPLE batches (>100 recipients) this is NOT atomic:
    // a throw on batch N leaves batches 1..N-1 already sent with no resume
    // cursor. That partial-send-then-500 is Tier-4, trigger-gated on recipient
    // volume (no continuation at v1 — see plan.md Risks); moot at v1's single
    // chunk.
    const { error } = await resend.batch.send(messages);
    if (error) {
      throw new Error(`Resend batch error: ${error.name}: ${error.message}`);
    }
    sent += messages.length;
  }

  console.log(`email-digest: sent ${sent} messages (${rows.length} listings)`);
  return { status: 'sent', rows: rows.length, recipients: recipients.length, sent };
}
