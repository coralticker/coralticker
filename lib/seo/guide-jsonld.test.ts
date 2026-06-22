import { test } from 'node:test';
import assert from 'node:assert/strict';
import { buildGuideJsonLd } from './guide-jsonld.ts';

const SITE = 'https://coralticker.com';

test('Article shape: headline, url, Person author, dateModified — NO offers', () => {
  const article = buildGuideJsonLd({
    siteUrl: SITE,
    slug: 'most-hunted-acros-2026',
    title: 'The most-hunted acros of 2026.',
    description: 'A short list of the acros worth waiting for.',
    updated: '2026-06-21',
  })[0] as Record<string, unknown>;

  assert.equal(article['@type'], 'Article');
  assert.equal(article.url, `${SITE}/guides/most-hunted-acros-2026`);
  assert.deepEqual(article.author, { '@type': 'Person', name: 'Jon' });
  assert.equal(article.dateModified, '2026-06-21');
  // The deceptive-rich-result guard: never an aggregate price block on a guide.
  assert.equal(article.offers, undefined);
  assert.equal(article.itemListElement, undefined);
});

test('absent description + updated → fields omitted, not emitted empty', () => {
  const article = buildGuideJsonLd({
    siteUrl: SITE,
    slug: 'x',
    title: 'X.',
    description: null,
    updated: '',
  })[0] as Record<string, unknown>;
  assert.equal(article.description, undefined);
  assert.equal(article.dateModified, undefined);
});
