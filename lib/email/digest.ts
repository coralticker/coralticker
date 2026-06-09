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
// SCAFFOLD IS NOT THIS FILE: the surrounding HTML email document (doctype,
// table layout for mail-client compat, hero lockup, footer chrome, Hunter-
// waitlist CTA seed) is a /brand-manager copy/layout artifact + /lead-frontend
// co-sign, pending into CTK-136/. This file builds the FIELD-LEVEL render (the
// listing lines) + the CAN-SPAM footer; wrapInterimDoc() below is an explicitly
// interim, un-branded document wrapper so the send pipe is end-to-end testable
// now. It is REPLACED by the real scaffold before first ship.
//
// Testability: the pure builders (buildFields, buildLine, groupByVendor,
// buildListingsHtml, buildFooter, listUnsubscribeHeaders, buildSubject,
// wrapInterimDoc) import clean with no env. The DB fetches and the Resend send
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
}

export interface Recipient {
  email: string;
  token: string;
}

// Resend batch endpoint caps at 100 messages per call.
const BATCH_SIZE = 100;

// Brand forest accent (tailwind.config.ts forest #1B5E20), mirrored for the
// now-value bold-forest field render (decision #75). The full brand token set
// is the deferred scaffold's concern; this is the one field-level token.
const FOREST = '#1B5E20';

// CAN-SPAM requires a physical postal address on every commercial send. This is
// JON-SIDE INPUT before first send (plan.md success criterion + Dependencies) —
// the loud placeholder makes a premature ship impossible to miss in the body.
const POSTAL_ADDRESS_PLACEHOLDER =
  '[POSTAL ADDRESS REQUIRED — Jon-side input before first send, CTK-136 CAN-SPAM footer]';

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
// field construction; formatValue()'s channel-neutral "was X, now Y" then
// carries it through the shared primitive.
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

// One listing line: bold coral name, em-dash, then the formatDataRow() render.
// raw_title is HTML-escaped (vendor-controlled); the wrapping <strong> is ours.
export function buildLine(row: DigestRow, now: Date): string {
  return `<strong>${htmlEscape(row.raw_title)}</strong> — ${formatDataRow(buildFields(row), now)}`;
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
// Markup is intentionally minimal/semantic — the field-level brand render (bold
// name, struck/forest prices) lives in the lines; the surrounding layout chrome
// is the deferred /brand-manager + /lead-frontend scaffold's concern.
export function buildListingsHtml(rows: DigestRow[], now: Date): string {
  const groups = groupByVendor(rows);
  return groups
    .map((group) => {
      const n = group.rows.length;
      const header = `<h2>${htmlEscape(group.vendor)} — ${n} drop${n === 1 ? '' : 's'}</h2>`;
      const lines = group.rows
        .map((row) => `<p>${buildLine(row, now)}</p>`)
        .join('\n');
      return `${header}\n${lines}`;
    })
    .join('\n');
}

// CAN-SPAM footer: a working per-recipient unsubscribe link + the physical
// postal address. This is the ONLY per-recipient element of the body (Q-5 shape
// — render the listings once, vary only the footer link per recipient). Richer
// footer copy ("you're getting this because…") is the deferred scaffold's lane.
export function buildFooter(token: string): string {
  return [
    `<p><a href="${unsubscribeUrl(token)}">Unsubscribe</a></p>`,
    `<p>${POSTAL_ADDRESS_PLACEHOLDER}</p>`,
  ].join('\n');
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

// INTERIM, UN-BRANDED document wrapper — REPLACED by the /brand-manager +
// /lead-frontend HTML email scaffold (hero lockup, table layout, chrome, Hunter
// CTA seed) before first ship. It exists only so the send pipe is end-to-end
// exercisable this session (the dry-run path logs a real, valid HTML document).
// Do NOT treat this as the digest's visual design.
export function wrapInterimDoc(contentHtml: string): string {
  return `<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body>
<!-- INTERIM scaffold (CTK-136) — replaced by /brand-manager + /lead-frontend before first ship -->
${contentHtml}
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
           event, event_at, first_seen_at, vendor_display_name
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
      html: wrapInterimDoc(`${listingsHtml}\n${buildFooter(r.token)}`),
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
