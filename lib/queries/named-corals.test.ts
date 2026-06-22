// Pure-mapper coverage for getNamedCoralBySlug's row -> NamedCoral step. The
// function itself can't be loaded here (react / next/cache / import-time
// NEON_DATABASE_URL read behind '@/' aliases — search.test.ts documents the same
// wall), so the testable contract lives in named-coral-row.ts. These assertions
// fail if the lore/genus passthrough or the description coercion ever regresses.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mapNamedCoralRow } from './named-coral-row.ts';

const baseRow = {
  id: 1,
  slug: 'homewrecker',
  canonical_name: 'Homewrecker',
  coral_type: 'SPS',
  genus: 'Acropora',
  lore: 'A tenuis with a cult following.',
  origin_vendor: 'WWC',
  source_urls: ['https://example.com'],
  requires_vendor_prefix: false,
  active: true,
};

test('mapNamedCoralRow: carries lore + genus through to the mapped coral', () => {
  const coral = mapNamedCoralRow(baseRow);
  assert.equal(coral.genus, 'Acropora');
  assert.equal(coral.lore, 'A tenuis with a cult following.');
});

test('mapNamedCoralRow: null lore + genus are valid passthrough values', () => {
  const coral = mapNamedCoralRow({ ...baseRow, lore: null, genus: null });
  assert.equal(coral.genus, null);
  assert.equal(coral.lore, null);
});

test('mapNamedCoralRow: description is always coerced to null', () => {
  // Hosted named_corals has no description column; the field is synthesized null.
  const coral = mapNamedCoralRow(baseRow);
  assert.equal(coral.description, null);
});

test('mapNamedCoralRow: other row fields pass through unchanged', () => {
  const coral = mapNamedCoralRow(baseRow);
  assert.equal(coral.slug, 'homewrecker');
  assert.equal(coral.canonical_name, 'Homewrecker');
  assert.equal(coral.active, true);
  assert.deepEqual(coral.source_urls, ['https://example.com']);
});
