// <DataRow> emits a separator only between bound fields, so testing that a
// suppressed Origin field is OMITTED from the array proves the em-dash collapse
// without needing a JSX render harness.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { buildLineageFields } from './lineage-fields.ts';
import type { NamedCoral } from '@/lib/queries/named-corals';

// Helper — only the four columns buildLineageFields() reads are load-bearing
// for these tests; the rest are constants on the NamedCoral row.
function coral(overrides: Partial<NamedCoral>): NamedCoral {
  return {
    id: 1,
    slug: 'test-coral',
    canonical_name: 'Test Coral',
    coral_type: null,
    genus: null,
    lore: null,
    origin_vendor: null,
    source_urls: null,
    requires_vendor_prefix: false,
    active: true,
    has_ever_listed: true,
    ...overrides,
  };
}

test('buildLineageFields: both columns null → empty array (em-dash collapse: zero separators)', () => {
  const fields = buildLineageFields(coral({}));
  assert.equal(fields.length, 0);
});

test('buildLineageFields: type acronym only → 1 field (em-dash collapse: zero separators)', () => {
  const fields = buildLineageFields(coral({ coral_type: 'SPS' }));
  assert.equal(fields.length, 1);
  assert.deepEqual(fields[0], { label: 'Type', value: 'SPS' });
});

test('buildLineageFields: type category-word only → 1 field, Title Case applied', () => {
  const fields = buildLineageFields(coral({ coral_type: 'zoa' }));
  assert.equal(fields.length, 1);
  assert.deepEqual(fields[0], { label: 'Type', value: 'Zoa' });
});

test('buildLineageFields: type binomial → italic kind on Type field', () => {
  const fields = buildLineageFields(
    coral({ coral_type: 'Acropora tenuis' }),
  );
  assert.equal(fields.length, 1);
  assert.deepEqual(fields[0], {
    label: 'Type',
    value: { kind: 'italic', value: 'Acropora tenuis' },
  });
});

test('buildLineageFields: type + sentinel community/canonical origin → 1 field (Origin suppressed, em-dash auto-collapsed)', () => {
  // The load-bearing sentinel-suppression test. <DataRow> would interleave a
  // separator between the Type and Origin fields if both were bound; with
  // Origin suppressed at this boundary, the field array shrinks to 1 entry
  // and the separator can't render.
  const fields = buildLineageFields(
    coral({ coral_type: 'SPS', origin_vendor: 'community/canonical' }),
  );
  assert.equal(fields.length, 1);
  assert.deepEqual(fields[0], { label: 'Type', value: 'SPS' });
});

test('buildLineageFields: type + single-value origin → 2 fields, originator expanded', () => {
  const fields = buildLineageFields(
    coral({ coral_type: 'SPS', origin_vendor: 'WWC' }),
  );
  assert.equal(fields.length, 2);
  assert.deepEqual(fields[0], { label: 'Type', value: 'SPS' });
  assert.deepEqual(fields[1], {
    label: 'Origin',
    value: 'World Wide Corals',
  });
});

test('buildLineageFields: type + compound origin Tyree/Reeffarmers → 2 fields, compound display joined', () => {
  // Tyree/Reeffarmers exercises both the compound-split branch AND the
  // Reeffarmers standalone-component-render branch in one row.
  const fields = buildLineageFields(
    coral({ coral_type: 'LPS', origin_vendor: 'Tyree/Reeffarmers' }),
  );
  assert.equal(fields.length, 2);
  assert.deepEqual(fields[0], { label: 'Type', value: 'LPS' });
  assert.deepEqual(fields[1], {
    label: 'Origin',
    value: 'Steve Tyree / Reeffarmers',
  });
});

test('buildLineageFields: origin-only (type null) → 1 field, no Type slot', () => {
  const fields = buildLineageFields(coral({ origin_vendor: 'ORA' }));
  assert.equal(fields.length, 1);
  assert.deepEqual(fields[0], { label: 'Origin', value: 'ORA' });
});

test('buildLineageFields: origin sentinel + type null → empty array', () => {
  // Both contributors collapse — type null skips, sentinel suppresses Origin.
  const fields = buildLineageFields(
    coral({ origin_vendor: 'community/canonical' }),
  );
  assert.equal(fields.length, 0);
});

test('buildLineageFields: empty-string drift on both fields → empty array (truthy guard)', () => {
  // Defensive — truthy guards (not !== null) catch empty-string drift in DB
  // columns. A bound-but-blank field would otherwise render `Type. ` with
  // nothing after, breaking em-dash collapse + chrome register.
  const fields = buildLineageFields(
    coral({ coral_type: '', origin_vendor: '' }),
  );
  assert.equal(fields.length, 0);
});
