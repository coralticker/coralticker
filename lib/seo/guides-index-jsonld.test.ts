import { test } from 'node:test';
import assert from 'node:assert/strict';
import { buildGuidesIndexJsonLd } from './guides-index-jsonld.ts';

const SITE = 'https://coralticker.com';

test('CollectionPage shape: ItemList of guide pages, NO offers/prices', () => {
  const page = buildGuidesIndexJsonLd({
    siteUrl: SITE,
    guides: [
      { slug: 'most-hunted-acros-2026', title: 'The most-hunted acros of 2026.' },
      { slug: 'beginner-softies', title: 'Softies that survive a new tank.' },
    ],
  })[0] as Record<string, unknown>;

  assert.equal(page['@type'], 'CollectionPage');
  assert.equal(page.url, `${SITE}/guides`);
  // The deceptive-rich-result guard: an editorial index never carries prices.
  assert.equal(page.offers, undefined);

  const list = page.mainEntity as Record<string, unknown>;
  assert.equal(list['@type'], 'ItemList');
  const items = list.itemListElement as Array<Record<string, unknown>>;
  assert.equal(items.length, 2);
  assert.deepEqual(items[0], {
    '@type': 'ListItem',
    position: 1,
    url: `${SITE}/guides/most-hunted-acros-2026`,
    name: 'The most-hunted acros of 2026.',
  });
  // Order + position mirror the rendered (sorted) list, 1-indexed.
  assert.equal(items[1]?.position, 2);
});

test('empty guide list → empty ItemList, not a crash or null', () => {
  const page = buildGuidesIndexJsonLd({ siteUrl: SITE, guides: [] })[0] as Record<
    string,
    unknown
  >;
  const list = page.mainEntity as Record<string, unknown>;
  assert.deepEqual(list.itemListElement, []);
});
