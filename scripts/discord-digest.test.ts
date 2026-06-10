// scripts/discord-digest.test.ts
//
// Pure-builder coverage for the CTK-011 Discord daily digest — field
// derivation (listing-card.tsx parity), Discord adapter styling, vendor
// grouping/ordering, N=3 cap + honest tails, and the 4096 defensive trim.
// No DB, no webhook — fetchRows/main are out of test scope (the RPC is
// smoke-tested at migration apply; the POST at first-ship per INV-01).

import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  buildDescription,
  buildEmbed,
  buildFields,
  buildLine,
  buildTitle,
  escapeDiscordMd,
  groupByVendor,
  type DigestRow,
} from './discord-digest.ts';

const NOW = new Date('2026-06-04T13:21:00Z');

function row(overrides: Partial<DigestRow>): DigestRow {
  return {
    id: 1,
    raw_title: 'Test Coral',
    current_price: '50.00',
    compare_at_price: null,
    prior_price: null,
    event: 'just-listed',
    event_at: '2026-06-04T10:21:00Z',
    first_seen_at: '2026-06-04T10:21:00Z',
    vendor_display_name: 'WWC',
    product_url: null,
    ...overrides,
  };
}

test('just-listed line: bold name + bare Price + Listed relative-time', () => {
  assert.equal(
    buildLine(row({}), NOW),
    '**Test Coral** — Price. $50.00 — Listed. 3 hours ago',
  );
});

test('product_url markdown-links the bold name (https only, <>-wrapped); null/non-https unlinked', () => {
  assert.equal(
    buildLine(row({ product_url: 'https://wwc.example/p/test-coral' }), NOW),
    '[**Test Coral**](<https://wwc.example/p/test-coral>) — Price. $50.00 — Listed. 3 hours ago',
  );
  // null -> unlinked
  assert.equal(
    buildLine(row({ product_url: null }), NOW),
    '**Test Coral** — Price. $50.00 — Listed. 3 hours ago',
  );
  // non-https / dangerous scheme -> unlinked (F3)
  assert.equal(
    buildLine(row({ product_url: 'javascript:alert(1)' }), NOW),
    '**Test Coral** — Price. $50.00 — Listed. 3 hours ago',
  );
});

test('bracketed coral name + paren in URL survive the masked link (F1)', () => {
  // ] in the name is escaped so it can't terminate [text]; the URL is <>-wrapped
  // so ')' in the query string can't terminate the (target).
  assert.equal(
    buildLine(
      row({ raw_title: 'Acro [WYSIWYG] Colony', product_url: 'https://v.example/p?variant=(red)&r=ct' }),
      NOW,
    ),
    '[**Acro \\[WYSIWYG\\] Colony**](<https://v.example/p?variant=(red)&r=ct>) — Price. $50.00 — Listed. 3 hours ago',
  );
});

test('price-dropped line: was-value struck, new value bare', () => {
  const line = buildLine(
    row({ event: 'price-dropped', prior_price: '400.00', current_price: '50.00' }),
    NOW,
  );
  assert.equal(line, '**Test Coral** — Price. ~~$400.00~~ $50.00 — Listed. 3 hours ago');
});

test('vendor-markdown at >=5%: was-value struck', () => {
  const fields = buildFields(row({ compare_at_price: '89.00', current_price: '49.00' }));
  assert.deepEqual(fields[0], {
    label: 'Price',
    value: { kind: 'vendor-markdown', oldValue: '~~$89.00~~', newValue: '$49.00' },
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
    '**Test Coral** — Price. price on request — Listed. 3 hours ago',
  );
});

test('back-in-stock row gets Back label on event_at', () => {
  const line = buildLine(row({ event: 'back-in-stock' }), NOW);
  assert.equal(line, '**Test Coral** — Price. $50.00 — Back. 3 hours ago');
});

test('discord markdown metacharacters escaped in coral names', () => {
  assert.equal(escapeDiscordMd('OG *Bounce* ~Shroom~ #4'), 'OG \\*Bounce\\* \\~Shroom\\~ #4');
  assert.ok(buildLine(row({ raw_title: 'A*B' }), NOW).startsWith('**A\\*B**'));
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
    row({ id: 1, event: 'just-listed', event_at: '2026-06-04T12:00:00Z' }),
    row({ id: 2, event: 'price-dropped', event_at: '2026-06-04T08:00:00Z' }),
    row({ id: 3, event: 'back-in-stock', event_at: '2026-06-04T09:00:00Z' }),
    row({ id: 4, event: 'price-dropped', event_at: '2026-06-04T11:00:00Z' }),
  ]);
  assert.deepEqual(
    groups[0]!.rows.map((r) => r.id),
    [4, 2, 3, 1],
  );
});

test('per-vendor cap at 3 with honest overflow tail', () => {
  const rows = [1, 2, 3, 4, 5].map((id) =>
    row({ id, raw_title: `Coral ${id}`, event_at: `2026-06-04T0${id}:00:00Z` }),
  );
  const description = buildDescription(rows, NOW);
  assert.match(description, /^\*\*WWC\*\* — 5 drops\n/);
  assert.equal(description.split('\n').length, 5); // header + 3 lines + tail
  // Tail is a masked markdown link to /new (bare domains don't auto-link in
  // embed descriptions); link text stays the bare domain.
  assert.match(
    description,
    /\n\+ 2 more at \[coralticker\.com\]\(<https:\/\/coralticker\.com\/new>\)$/,
  );
});

test('vendor at or under cap renders all lines, no tail', () => {
  const description = buildDescription([row({})], NOW);
  assert.match(description, /^\*\*WWC\*\* — 1 drop\n/);
  assert.ok(!description.includes('more at'));
});

// 4096 stays a literal here on purpose (/code-review #10 disposition):
// it pins Discord's embed-description API contract independently of the
// script's EMBED_DESCRIPTION_CAP constant — if the constant ever drifts,
// this test fails instead of drifting with it.
test('defensive trim collapses quietest vendors and stays under 4096', () => {
  // 40 vendors x 3 long-titled rows ≈ well over 4096 — forces collapse.
  const rows: DigestRow[] = [];
  let id = 0;
  for (let v = 0; v < 40; v++) {
    for (let i = 0; i < 3; i++) {
      rows.push(
        row({
          id: ++id,
          vendor_display_name: `Vendor ${String(v).padStart(2, '0')}`,
          raw_title: `Extremely Long Hypothetical Coral Trade Name ${id} Edition`,
        }),
      );
    }
  }
  const description = buildDescription(rows, NOW);
  assert.ok(description.length <= 4096, `length ${description.length}`);
  // Busiest-first ordering is count-equal here, so name-asc: Vendor 00
  // stays fully rendered; collapsed groups carry the full-count tail.
  assert.match(description, /\*\*Vendor 00\*\* — 3 drops\n\*\*Extremely/);
  // Collapsed-group tail (the capped renderGroup branch) carries the same
  // masked /new link as the overflow tail.
  assert.match(
    description,
    /\*\*Vendor 39\*\* — 3 drops\n\+ 3 more at \[coralticker\.com\]\(<https:\/\/coralticker\.com\/new>\)/,
  );
});

test('empty rows produce empty description (caller skips the post)', () => {
  assert.equal(buildDescription([], NOW), '');
});

test('embed url field links the title home (wordmark-home parity)', () => {
  assert.deepEqual(buildEmbed('CoralTicker — daily drops 2026-06-04', 'body'), {
    title: 'CoralTicker — daily drops 2026-06-04',
    description: 'body',
    url: 'https://coralticker.com',
  });
});

test('title carries the US Eastern date', () => {
  assert.equal(buildTitle(NOW), 'CoralTicker — daily drops 2026-06-04');
  // Divergence case: 02:00 UTC is already June 5 in UTC but still
  // June 4 evening in ET — a late manual dispatch must not date-skip.
  assert.equal(
    buildTitle(new Date('2026-06-05T02:00:00Z')),
    'CoralTicker — daily drops 2026-06-04',
  );
});
