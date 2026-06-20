// scripts/discord-digest.ts
//
// CTK-011 — daily drop digest to the public Discord #drops channel.
// Standalone Node script per the ratified 2026-06-04 build shape: one
// query, one embed, one webhook POST. No notifier_state, no
// notification_log — the daily cron cadence is its own dedup (a missed
// day is a missed post, not a backfill obligation).
//
// Source: get_listing_lead_event(NULL, 24, NULL, NULL) — migration 0030,
// fleet-wide 24h window, uncapped (per-vendor top-N below does the render
// compression; uncapped input keeps the "+ N more" tail counts honest).
// Lead-event precedence (price-dropped > back-in-stock > just-listed) is
// inherited from the RPC's ranking — one row per listing, lead event only;
// nothing here re-derives it. OOS rows never arrive: all three RPC arms
// filter in_stock = true (deal-buyer canon, branding-guide.md §"State
// markers" — the OOS adapter shape is cited in plan.md if a variant ever
// renders one).
//
// INV-01 channel parity: each listing line renders through formatDataRow()
// (lib/format/data-row.ts) — same field order, same labels, same em-dash
// separator as the web <DataRow>. This file is the Discord channel-adapter
// on top: markdown bold on the coral name, ~~strikethrough~~ on the
// was-value of price-drop-new / vendor-markdown fields (decision #75),
// applied at field construction so the canonical shape still flows through
// the shared primitive. Field-derivation logic mirrors
// components/listing-card.tsx buildFields() — the Price precedence chain
// (price-drop-new > vendor-markdown-at->=5% > bare) and the
// 'price on request' null-price shape (auctions) are verbatim ports.
//
// Discord caps an embed description at 4096 chars. N=3 lines per vendor
// (Jon + /reef-lead lock 2026-06-04) fits all 11 vendors saturated; the
// defensive trim below collapses quietest-vendor groups to header+tail if
// a future vendor fleet outgrows that math, and logs what it dropped.
//
// Invocation:
//   workflow:  node --experimental-strip-types scripts/discord-digest.ts
//              (env: NEON_DATABASE_URL, DISCORD_WEBHOOK_URL)
//   local dry-run (no POST, no webhook needed):
//              node --env-file=.env --experimental-strip-types \
//                scripts/discord-digest.ts --dry-run

import { pathToFileURL } from 'node:url';
import { formatDataRow } from '../lib/format/data-row.ts';
import type { DataRowField } from '../components/ui/data-row';

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
  // The vendor's product page (the buy link). Returned by get_listing_lead_event
  // (migration 0030); the coral name becomes a markdown link to it. Nullable — a
  // row without a URL renders the name unlinked.
  product_url: string | null;
}

const EMBED_DESCRIPTION_CAP = 4096; // Discord hard limit per embed description
const PER_VENDOR_CAP = 3; // Jon + /reef-lead lock 2026-06-04

// Site links (email masthead wordmark-home parity, lib/email/digest.ts). The
// embed's url field makes the title link home; the "+ N more" tails link to
// /new because the overflow rows are last-24h lead events and /new is that
// exact surface (same RPC). Bare domains don't auto-link in embed
// descriptions, so the tail is a masked markdown link — <>-wrapped per the
// buy-link hardening below, link text stays the bare domain.
//
// Both site links carry ?ref=discord for first-touch channel attribution
// (CTK-158): a click→signup attributes to Discord. The param is read by
// middleware on any entry route (the homepage title + the /new tail both
// qualify), is first-touch (never overwrites an earlier channel), and is
// invisible to the reader. The link text stays the bare domain.
const SITE_URL = 'https://coralticker.com';
const TAIL_SITE = 'coralticker.com';
const TITLE_URL = `${SITE_URL}/?ref=discord`;
const TAIL_LINK = `[${TAIL_SITE}](<${SITE_URL}/new?ref=discord>)`;

// RPC precedence ranks, mirrored for within-vendor display order only —
// the lead-event CHOICE per listing already happened in the RPC.
const PRECEDENCE: Record<DigestRow['event'], number> = {
  'price-dropped': 1,
  'back-in-stock': 2,
  'just-listed': 3,
};

// Discord markdown metacharacters in vendor titles (coral names carry asterisks,
// underscores, and bracketed tags like [WYSIWYG] / (Rainbow) in the wild).
// Backslash first. The [ ] escapes are load-bearing for the masked buy-link: an
// unescaped ] in raw_title terminates the [link text] early and mangles the line.
export function escapeDiscordMd(text: string): string {
  return text.replace(/([\\*_~`|[\]])/g, '\\$1');
}

// Verbatim port of components/listing-card.tsx formatPrice — null price is
// the auction parse-time shape ('price on request', never a fake buy price
// per project canon). Neon's HTTP driver returns numerics as strings.
function formatPrice(value: number | string | null): string {
  if (value === null) return 'price on request';
  return `$${Number(value).toFixed(2)}`;
}

function asNumber(value: number | string | null): number | null {
  return value === null ? null : Number(value);
}

// Mirrors listing-card.tsx buildFields() Price precedence chain:
// price-drop-new > vendor-markdown (>=5% epsilon-guarded) > bare. The OOS
// 'invalidated' branch is intentionally absent — the RPC filters
// in_stock = true on all arms, so no OOS row can reach this adapter.
// Discord styling (~~ on the was-value) lands here at field construction;
// formatValue()'s channel-neutral adjacency shape (struck old + new, no words —
// card-parity, 2026-06-09) then carries it.
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
        oldValue: `~~${formatPrice(priorPrice)}~~`,
        newValue: formatPrice(currentPrice),
      },
    });
  } else if (
    compareAtPrice !== null &&
    currentPrice !== null &&
    // Subtract-then-compare with epsilon per listing-card.tsx (IEEE754
    // misses ~29% of clean integer-dollar 5% markdowns otherwise).
    compareAtPrice - currentPrice >= currentPrice * 0.05 - 1e-9
  ) {
    fields.push({
      label: 'Price',
      value: {
        kind: 'vendor-markdown',
        oldValue: `~~${formatPrice(compareAtPrice)}~~`,
        newValue: formatPrice(currentPrice),
      },
    });
  } else {
    fields.push({ label: 'Price', value: formatPrice(currentPrice) });
  }

  // Mirrors listing-card.tsx 'Listed' field (eventAt ?? firstSeenAt).
  // back-in-stock rows get the 'Back' label so the restock reads on the
  // line without a lead sentence (vendor is the group header here, so the
  // web card's "back in stock at {vendor}." lead has no slot).
  // Label ratified by /brand-manager 2026-06-06 — canon on lead-less
  // channel compositions only (branding-guide.md em-dash field vocabulary).
  fields.push({
    label: row.event === 'back-in-stock' ? 'Back' : 'Listed',
    value: {
      kind: 'relative-time',
      timestamp: row.event_at ?? row.first_seen_at,
    },
  });

  return fields;
}

// The bold coral name links to the vendor's product page via Discord markdown
// ([**name**](<url>)) — same buy-link destination as the web feed + email. A
// markdown link in an embed description renders clickable without a preview card.
// Hardening (CTK-136 /code-review F1+F3): the URL is wrapped in <> so a ')' in the
// query string can't terminate the (…) target early; escapeDiscordMd now escapes
// [ ] so a bracketed coral name can't terminate the [text]; and only https URLs
// linkify (a non-https / dangerous-scheme product_url renders the name unlinked).
export function buildLine(row: DigestRow, now: Date): string {
  const name = `**${escapeDiscordMd(row.raw_title)}**`;
  const named =
    row.product_url && /^https:\/\//i.test(row.product_url)
      ? `[${name}](<${row.product_url}>)`
      : name;
  return `${named} — ${formatDataRow(buildFields(row), now)}`;
}

interface VendorGroup {
  vendor: string;
  rows: DigestRow[];
}

// Vendors busiest-first (count desc, name asc tiebreak); within a vendor,
// precedence rank then newest-first.
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

function renderGroup(group: VendorGroup, now: Date, capped: boolean): string {
  const n = group.rows.length;
  const header = `**${escapeDiscordMd(group.vendor)}** — ${n} drop${n === 1 ? '' : 's'}`;
  if (capped) {
    return `${header}\n+ ${n} more at ${TAIL_LINK}`;
  }
  const lines = group.rows.slice(0, PER_VENDOR_CAP).map((row) => buildLine(row, now));
  const overflow = n - PER_VENDOR_CAP;
  if (overflow > 0) {
    lines.push(`+ ${overflow} more at ${TAIL_LINK}`);
  }
  return [header, ...lines].join('\n');
}

export function buildDescription(rows: DigestRow[], now: Date): string {
  const groups = groupByVendor(rows);
  let rendered = groups.map((g) => renderGroup(g, now, false));
  let description = rendered.join('\n\n');

  // Defensive trim — N=3 x current fleet fits 4096 with headroom, but a
  // bulk-drop fleet expansion shouldn't 400 the POST or silently eat the
  // tail. Collapse quietest vendors (groups are busiest-first, so collapse
  // from the end) to header + honest full-count tail, loudly.
  for (let i = groups.length - 1; description.length > EMBED_DESCRIPTION_CAP && i >= 0; i--) {
    const group = groups[i];
    if (!group) continue; // noUncheckedIndexedAccess — unreachable within bounds
    console.log(
      `digest: over ${EMBED_DESCRIPTION_CAP} chars (${description.length}); collapsing ${group.vendor} (${group.rows.length} rows) to header+tail`,
    );
    rendered[i] = renderGroup(group, now, true);
    description = rendered.join('\n\n');
  }
  if (description.length > EMBED_DESCRIPTION_CAP) {
    // Every group already collapsed and still over — truncate hard, loudly.
    console.log(`digest: still over cap after collapsing all groups; hard-truncating`);
    description = `${description.slice(0, EMBED_DESCRIPTION_CAP - 1)}…`;
  }
  return description;
}

export function buildTitle(now: Date): string {
  // ET-anchored date, not UTC (/code-review #9 fold): at the 13:21 UTC
  // cron tick the two match, but a manual workflow_dispatch after 8pm ET
  // would stamp tomorrow's UTC date on today's drops. en-CA renders
  // ISO-shaped YYYY-MM-DD.
  const date = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'America/New_York',
  }).format(now);
  return `CoralTicker — daily drops ${date}`;
}

// The embed url field renders the title as a link home — the embed-level
// analogue of the email masthead's wordmark-home pattern (lib/email/digest.ts
// MASTHEAD). Exported so the field is assertable without running main().
export function buildEmbed(
  title: string,
  description: string,
): { title: string; description: string; url: string } {
  return { title, description, url: TITLE_URL };
}

async function fetchRows(): Promise<DigestRow[]> {
  // Dynamic import keeps lib/db/neon.ts's module-scope env throw out of
  // test runs (the pure builders above import clean with no env).
  const { getNeonSql } = await import('../lib/db/neon.ts');
  const sql = getNeonSql();
  const rows = await sql`
    SELECT id, raw_title, current_price, compare_at_price, prior_price,
           event, event_at, first_seen_at, vendor_display_name, product_url
    FROM get_listing_lead_event(NULL, 24, NULL, NULL)
  `;
  return rows as unknown as DigestRow[];
}

async function main(): Promise<number> {
  const dryRun = process.argv.includes('--dry-run');
  const now = new Date();

  const rows = await fetchRows();
  if (rows.length === 0) {
    // Near-impossible across 11 hourly-scraped vendors; if it happens,
    // skip the post rather than broadcast an empty embed.
    console.log('digest: 0 lead events in the 24h window; not posting');
    return 0;
  }

  const title = buildTitle(now);
  const description = buildDescription(rows, now);
  console.log(
    `digest: ${rows.length} rows, ${new Set(rows.map((r) => r.vendor_display_name)).size} vendors, ${description.length} chars`,
  );

  if (dryRun) {
    console.log(`\n${title}\n\n${description}`);
    return 0;
  }

  const webhookUrl = process.env.DISCORD_WEBHOOK_URL;
  if (!webhookUrl) {
    console.error('DISCORD_WEBHOOK_URL must be set (GH Actions secret; Jon-side gh secret set)');
    return 1;
  }

  // ?wait=true makes Discord return the created message (200 + body)
  // instead of fire-and-forget 204 — POST failures surface as non-ok.
  // URL() + searchParams survives a webhook URL that already carries
  // query params (/code-review #1 fold).
  const url = new URL(webhookUrl);
  url.searchParams.set('wait', 'true');
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ embeds: [buildEmbed(title, description)] }),
  });
  if (!response.ok) {
    console.error(`digest: webhook POST failed: HTTP ${response.status} ${await response.text()}`);
    return 1;
  }
  // 204-safe (/code-review #1 fold): only the 200-with-body shape carries
  // a message id; a 204 (e.g., wait param stripped upstream) has no JSON.
  if (response.status === 200) {
    const message = (await response.json()) as { id?: string };
    console.log(`digest: posted (message id ${message.id ?? 'unknown'})`);
  } else {
    console.log(`digest: posted (HTTP ${response.status}, no message body)`);
  }
  return 0;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().then(
    (code) => process.exit(code),
    (err) => {
      console.error(`digest: ${err instanceof Error ? err.stack ?? err.message : err}`);
      process.exit(1);
    },
  );
}
