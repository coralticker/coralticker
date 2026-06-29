// scripts/send_test_digest.ts
//
// DEV / EYEBALL HARNESS — not shipped, not a cron, not in the `npm test` glob.
// Renders the CTK-136 daily digest with the PRODUCTION builders and sends ONE
// copy to a single override address via the shared sendEmail() wrapper. It
// BYPASSES the confirmed-recipient query, so it never touches the live
// subscriber list — use it to eyeball the scaffold in a real inbox
// (Gmail / Apple Mail / Outlook) before the cron's first scheduled fire.
//
// Run (key + DB url load from .env via node --env-file; never echoed to stdout):
//   node --env-file=.env --experimental-strip-types scripts/send_test_digest.ts you@example.com
//
// Flags:
//   --sample   use a fixed multi-shape fixture instead of the live 24h window
//              (price-drop / vendor-markdown / restock / bare / null-price auction).
//              Renders without touching the DB — handy when the live window is thin.
//
// Without RESEND_API_KEY in env, sendEmail() takes its off-prod dry-run path:
// it logs the envelope and sends nothing. Pass --env-file=.env to actually send.
//
// The unsubscribe link uses a throwaway token (fine for a design eyeball — it
// won't resolve to a real row). List-Unsubscribe headers are included so Gmail
// renders the same one-click affordance the real send carries.

import {
  buildListingsHtml,
  buildFooter,
  buildSubject,
  wrapDigestDoc,
  listUnsubscribeHeaders,
  type DigestRow,
} from '../lib/email/digest.ts';
import { sendEmail } from '../lib/email/send.ts';

const to = process.argv[2];
if (!to || !to.includes('@')) {
  console.error(
    'usage: node --env-file=.env --experimental-strip-types scripts/send_test_digest.ts <to-address> [--sample]',
  );
  process.exit(1);
}
const useSample = process.argv.includes('--sample');

function sampleRows(now: Date): DigestRow[] {
  const ago = (mins: number) => new Date(now.getTime() - mins * 60_000).toISOString();
  return [
    // WWC — CT-observed price drop + a bare in-stock (with escaped metachars)
    { id: 1, raw_title: 'WWC Pink Floyd Acropora', current_price: '650.00', compare_at_price: null, prior_price: '800.00', event: 'price-dropped', event_at: ago(120), first_seen_at: ago(11520), vendor_display_name: 'World Wide Corals', product_url: 'https://wwc.example/products/pink-floyd-acropora', bulk_cluster: false },
    { id: 2, raw_title: 'WWC OG Bounce <Mushroom> & "Rainbow"', current_price: '120.00', compare_at_price: null, prior_price: null, event: 'just-listed', event_at: ago(60), first_seen_at: ago(60), vendor_display_name: 'World Wide Corals', product_url: 'https://wwc.example/products/og-bounce?variant=1&x=2', bulk_cluster: false },
    // TSA — vendor-set markdown
    { id: 3, raw_title: 'TSA Disco Hammer', current_price: '149.00', compare_at_price: '199.00', prior_price: null, event: 'just-listed', event_at: ago(180), first_seen_at: ago(180), vendor_display_name: 'Top Shelf Aquatics', product_url: 'https://tsa.example/products/disco-hammer', bulk_cluster: false },
    // JF — restock + null-price (auction / price-on-request); null product_url -> unlinked fallback
    { id: 4, raw_title: 'JF Bombshell Blasto', current_price: '90.00', compare_at_price: null, prior_price: null, event: 'back-in-stock', event_at: ago(30), first_seen_at: ago(28800), vendor_display_name: 'Jason Fox Signature Corals', product_url: 'https://jf.example/products/bombshell-blasto', bulk_cluster: false },
    { id: 5, raw_title: 'JF Reverse Sunset Monti', current_price: null, compare_at_price: null, prior_price: null, event: 'just-listed', event_at: ago(240), first_seen_at: ago(240), vendor_display_name: 'Jason Fox Signature Corals', product_url: null, bulk_cluster: false },
  ];
}

async function realRows(): Promise<DigestRow[]> {
  const { getNeonSql } = await import('../lib/db/neon.ts');
  const sql = getNeonSql();
  const rows = await sql`
    SELECT id, raw_title, current_price, compare_at_price, prior_price,
           event, event_at, first_seen_at, vendor_display_name, product_url
    FROM get_listing_lead_event(NULL, 24, NULL, NULL)
  `;
  return rows as unknown as DigestRow[];
}

const now = new Date();
const rows = useSample ? sampleRows(now) : await realRows();
if (rows.length === 0) {
  console.error('no lead events in the live 24h window — re-run with --sample for a fixture');
  process.exit(1);
}

const subject = buildSubject(now);
const token = 'tok_test-eyeball';
const html = wrapDigestDoc(buildListingsHtml(rows, now), buildFooter(token), subject);

const { sent } = await sendEmail({ to, subject, html, headers: listUnsubscribeHeaders(token) });
console.log(
  sent
    ? `sent ${rows.length}-listing digest to ${to} (subject: ${subject})`
    : `NOT sent — keyless dry-run or send error (see log above). Add --env-file=.env to send for real.`,
);
