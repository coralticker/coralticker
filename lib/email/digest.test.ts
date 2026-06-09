// lib/email/digest.test.ts
//
// Pure-builder coverage for the CTK-136 email daily digest — field derivation
// (Price precedence chain, parity with scripts/discord-digest.ts), HTML adapter
// styling (semantic <del> + bold-forest), vendor grouping/ordering, the
// formatDataRow() INV-01 line shape, the CAN-SPAM footer + per-recipient
// unsubscribe link, the RFC 8058 List-Unsubscribe headers, and the ET-anchored
// subject. No DB, no Resend — fetchRows/fetchRecipients/runEmailDigest are out
// of test scope (the RPC is smoke-tested at migration apply; the batch send at
// first-ship per INV-01 check-cadence 2).

import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  buildFields,
  buildFooter,
  buildLine,
  buildListingsHtml,
  buildSubject,
  groupByVendor,
  htmlEscape,
  listUnsubscribeHeaders,
  type DigestRow,
} from './digest.ts';

const NOW = new Date('2026-06-09T13:00:00Z');

function row(overrides: Partial<DigestRow>): DigestRow {
  return {
    id: 1,
    raw_title: 'Test Coral',
    current_price: '50.00',
    compare_at_price: null,
    prior_price: null,
    event: 'just-listed',
    event_at: '2026-06-09T10:00:00Z',
    first_seen_at: '2026-06-09T10:00:00Z',
    vendor_display_name: 'WWC',
    ...overrides,
  };
}

test('just-listed line: bold name + bare Price + Listed relative-time', () => {
  assert.equal(
    buildLine(row({}), NOW),
    '<strong>Test Coral</strong> — Price. $50.00 — Listed. 3 hours ago',
  );
});

test('price-dropped line: was-value in <del>, now-value bold-forest', () => {
  const line = buildLine(
    row({ event: 'price-dropped', prior_price: '400.00', current_price: '50.00' }),
    NOW,
  );
  assert.equal(
    line,
    '<strong>Test Coral</strong> — Price. was <del>$400.00</del>, now <strong style="color:#1B5E20;font-weight:700;">$50.00</strong> — Listed. 3 hours ago',
  );
});

test('vendor-markdown at >=5%: was-value struck, now-value bold-forest', () => {
  const fields = buildFields(row({ compare_at_price: '89.00', current_price: '49.00' }));
  assert.deepEqual(fields[0], {
    label: 'Price',
    value: {
      kind: 'vendor-markdown',
      oldValue: '<del>$89.00</del>',
      newValue: '<strong style="color:#1B5E20;font-weight:700;">$49.00</strong>',
    },
  });
});

test('vendor-markdown epsilon: clean integer-dollar 5% markdown qualifies', () => {
  // 3.15 vs 3.00 is exactly 5% — the IEEE754 multiply form misses it.
  const fields = buildFields(row({ compare_at_price: '3.15', current_price: '3.00' }));
  assert.equal((fields[0]!.value as { kind: string }).kind, 'vendor-markdown');
});

test('compare_at under 5% renders bare Price (no markdown field)', () => {
  const fields = buildFields(row({ compare_at_price: '51.00', current_price: '50.00' }));
  assert.deepEqual(fields[0], { label: 'Price', value: '$50.00' });
});

test('price-drop-new wins over vendor-markdown when both apply', () => {
  const fields = buildFields(
    row({ prior_price: '100.00', compare_at_price: '120.00', current_price: '50.00' }),
  );
  assert.equal((fields[0]!.value as { kind: string }).kind, 'price-drop-new');
});

test('null price renders "price on request" (auction shape)', () => {
  assert.equal(
    buildLine(row({ current_price: null }), NOW),
    '<strong>Test Coral</strong> — Price. price on request — Listed. 3 hours ago',
  );
});

test('back-in-stock row gets Back label on event_at', () => {
  const line = buildLine(row({ event: 'back-in-stock' }), NOW);
  assert.equal(line, '<strong>Test Coral</strong> — Price. $50.00 — Back. 3 hours ago');
});

test('HTML metacharacters escaped in coral names', () => {
  assert.equal(htmlEscape('OG <Bounce> & "Shroom" #4'), 'OG &lt;Bounce&gt; &amp; &quot;Shroom&quot; #4');
  assert.ok(buildLine(row({ raw_title: 'A<B&C' }), NOW).startsWith('<strong>A&lt;B&amp;C</strong>'));
});

test('vendors ordered busiest-first, name-asc tiebreak', () => {
  const groups = groupByVendor([
    row({ id: 1, vendor_display_name: 'TSA' }),
    row({ id: 2, vendor_display_name: 'WWC' }),
    row({ id: 3, vendor_display_name: 'WWC' }),
    row({ id: 4, vendor_display_name: 'JF' }),
  ]);
  assert.deepEqual(
    groups.map((g) => g.vendor),
    ['WWC', 'JF', 'TSA'],
  );
});

test('within-vendor order: precedence rank, then newest-first', () => {
  const groups = groupByVendor([
    row({ id: 1, event: 'just-listed', event_at: '2026-06-09T12:00:00Z' }),
    row({ id: 2, event: 'price-dropped', event_at: '2026-06-09T08:00:00Z' }),
    row({ id: 3, event: 'back-in-stock', event_at: '2026-06-09T09:00:00Z' }),
    row({ id: 4, event: 'price-dropped', event_at: '2026-06-09T11:00:00Z' }),
  ]);
  assert.deepEqual(
    groups[0]!.rows.map((r) => r.id),
    [4, 2, 3, 1],
  );
});

test('listings html: vendor header (pluralized) + one <p> line per listing, no cap', () => {
  const rows = [1, 2, 3, 4, 5].map((id) =>
    row({ id, raw_title: `Coral ${id}`, event_at: `2026-06-09T0${id}:00:00Z` }),
  );
  const html = buildListingsHtml(rows, NOW);
  assert.match(html, /<h2>WWC — 5 drops<\/h2>/);
  // Email has no per-vendor cap (unlike the Discord N=3) — all 5 lines render.
  assert.equal((html.match(/<p>/g) ?? []).length, 5);
  assert.ok(!html.includes('more at'));
});

test('single-drop vendor header is singular', () => {
  assert.match(buildListingsHtml([row({})], NOW), /<h2>WWC — 1 drop<\/h2>/);
});

test('empty rows produce empty listings html (caller skips the send)', () => {
  assert.equal(buildListingsHtml([], NOW), '');
});

test('footer carries per-recipient unsubscribe link + postal-address placeholder', () => {
  const footer = buildFooter('tok_abc-123');
  assert.match(footer, /<a href="https:\/\/coralticker\.com\/unsubscribe\?t=tok_abc-123">Unsubscribe<\/a>/);
  // The loud placeholder is the first-ship gate — it must be impossible to miss.
  assert.match(footer, /POSTAL ADDRESS REQUIRED/);
});

test('List-Unsubscribe headers: angle-bracketed target + one-click post', () => {
  const headers = listUnsubscribeHeaders('tok_abc-123');
  assert.equal(
    headers['List-Unsubscribe'],
    '<https://coralticker.com/unsubscribe?t=tok_abc-123>',
  );
  assert.equal(headers['List-Unsubscribe-Post'], 'List-Unsubscribe=One-Click');
});

test('subject carries the US Eastern date', () => {
  assert.equal(buildSubject(NOW), 'CoralTicker — daily drops 2026-06-09');
  // Divergence case: 02:00 UTC is already the next day in UTC but still the
  // prior evening in ET — a late fire must not date-skip.
  assert.equal(
    buildSubject(new Date('2026-06-10T02:00:00Z')),
    'CoralTicker — daily drops 2026-06-09',
  );
});
