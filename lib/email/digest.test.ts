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
  wrapDigestDoc,
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
    product_url: null,
    ...overrides,
  };
}

test('just-listed line: bold name + bare Price + Listed relative-time', () => {
  assert.equal(
    buildLine(row({}), NOW),
    '<strong>Test Coral</strong> — Price. $50.00 — Listed. 3 hours ago',
  );
});

test('product_url links the bold coral name (new tab, ink + underline)', () => {
  const line = buildLine(row({ product_url: 'https://wwc.example/products/test-coral?v=1&x=2' }), NOW);
  assert.equal(
    line,
    '<a href="https://wwc.example/products/test-coral?v=1&amp;x=2" target="_blank" rel="noopener noreferrer" style="color:#1A1A1A;text-decoration:underline;"><strong>Test Coral</strong></a> — Price. $50.00 — Listed. 3 hours ago',
  );
});

test('null product_url renders the coral name unlinked (graceful fallback)', () => {
  assert.equal(
    buildLine(row({ product_url: null }), NOW),
    '<strong>Test Coral</strong> — Price. $50.00 — Listed. 3 hours ago',
  );
});

test('non-https product_url renders the name unlinked (F3 scheme allowlist)', () => {
  assert.equal(
    buildLine(row({ product_url: 'javascript:alert(1)' }), NOW),
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
    '<strong>Test Coral</strong> — Price. <del>$400.00</del> <strong style="color:#1B5E20;font-weight:700;">$50.00</strong> — Listed. 3 hours ago',
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
  // 3.15 vs 3.00 is exactly 5% — the IEEE754 multiply form misses it; the
  // subtract-then-epsilon form catches it.
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
  assert.match(html, /<span style="font-weight:700;">WWC<\/span> — 5 drops/);
  // Email has no per-vendor cap (unlike the Discord N=3) — all 5 lines render.
  assert.equal((html.match(/<p style=/g) ?? []).length, 5);
  assert.ok(!html.includes('more at'));
});

test('single-drop vendor header is singular', () => {
  assert.match(buildListingsHtml([row({})], NOW), /<span style="font-weight:700;">WWC<\/span> — 1 drop/);
});

test('empty rows produce empty listings html (caller skips the send)', () => {
  assert.equal(buildListingsHtml([], NOW), '');
});

test('footer: subjectless why-line + per-recipient one-click unsub + postal address + disclaimer', () => {
  const footer = buildFooter('tok_abc-123');
  assert.match(footer, /You confirmed your email for daily coral drops at coralticker\.com\./);
  assert.match(footer, /href="https:\/\/coralticker\.com\/unsubscribe\?t=tok_abc-123"/);
  assert.match(footer, /Unsubscribe\.<\/a>/);
  // CAN-SPAM requires a physical postal address.
  assert.match(footer, /PO Box 115, 221 Najoles Road, Millersville, MD 21108/);
  assert.match(footer, /Not affiliated with vendors\./);
  assert.ok(!/Last scrape/i.test(footer));
});

test('footer voice: no first-person on the email-digest surface (§1 surface boundary)', () => {
  const footer = buildFooter('tok_abc-123');
  assert.ok(!/\bI\b/.test(footer), 'no bare "I"');
  assert.ok(!/\bwe\b/i.test(footer), 'no "we"');
  assert.ok(!/\bJon\b/i.test(footer), 'no "Jon"');
});

test('wrapDigestDoc: branded document — wordmark-alone masthead, white bg, subject title', () => {
  const doc = wrapDigestDoc(
    buildListingsHtml([row({})], NOW),
    buildFooter('tok_abc-123'),
    buildSubject(NOW),
  );
  assert.match(doc, /<span style="font-weight:700;">coral<\/span><span style="font-weight:400;">ticker<\/span>/);
  // Wordmark links home, not underlined (newspaper-masthead pattern).
  assert.match(doc, /<a href="https:\/\/coralticker\.com" style="color:#1A1A1A;text-decoration:none;">/);
  // Tagline dropped on the daily surface.
  assert.ok(!/Never miss the drop/.test(doc), 'no tagline on the daily digest masthead');
  assert.match(doc, /background:#FFFFFF/);
  assert.match(doc, /<title>CoralTicker — daily drops 2026-06-09<\/title>/);
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
