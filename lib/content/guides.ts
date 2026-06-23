// Flat-file MDX guide store (CTK-162 scope c, open item #2 → MDX/flat-file).
// Guide bodies live in content/guides/<slug>.mdx with YAML frontmatter; prose is
// static, the embedded <CoralReference> blocks resolve live at render so prices
// are always current. No CMS — copy-writer edits the .mdx under /brand-manager
// and ships without an engineer in the loop.
//
// Server-only (fs). The .mdx files are traced into the serverless bundle via
// outputFileTracingIncludes in next.config.ts so the read works on Vercel, not
// just locally.

import fs from 'node:fs';
import path from 'node:path';
import matter from 'gray-matter';

const GUIDES_DIR = path.join(process.cwd(), 'content', 'guides');

export interface GuideFrontmatter {
  slug: string; // canonical, must match the filename (validated below)
  kind: string; // eyebrow KIND chunk, e.g. "BUYING GUIDE"
  updated: string; // editorial-revision date, YYYY-MM-DD (NOT a price-freshness claim)
  title: string; // declarative, carries its own terminal period (or ? if question-shaped)
  description?: string; // SERP meta; falls back to a derived line when absent
}

export interface Guide {
  frontmatter: GuideFrontmatter;
  body: string; // MDX source with frontmatter stripped
}

const MONTHS = [
  'JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN',
  'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC',
];

// Strip a single trailing period off a declarative title for use as an inline
// label (link text, SERP <title>) where the on-page period would read as a
// sentence-ender mid-line. Shared so the /guides SERP metaTitle and the
// /coral/[slug] "Featured in:" back-link strip identically — one rule, two sites.
export function stripTrailingPeriod(title: string): string {
  return title.replace(/\.$/, '');
}

// "2026-06-21" → "JUN 2026". Absolute month-year, never relative (D-4: relative
// time implies an auto-freshness the editorial layer doesn't have). String split
// (not Date) so it's tz-independent.
export function updatedMonthYear(updated: string): string {
  const [year, month] = updated.split('-');
  const m = Number(month);
  const name = m >= 1 && m <= 12 ? MONTHS[m - 1] : '';
  return name ? `${name} ${year}` : String(year ?? updated);
}

// gray-matter auto-parses an unquoted YAML ISO date (`updated: 2026-06-22`) into
// a JS Date — String()ing that yields the full `toString()` form (and a local-tz
// off-by-one). Coerce a Date back to YYYY-MM-DD via the UTC slice (gray-matter
// parses the date as midnight UTC, so the UTC date is the authored date) so the
// downstream updatedMonthYear string-split sees the shape it expects. Defends
// against future unquoted .mdx authoring — the fix lives at the read layer, not
// in each .mdx's quoting.
function normalizeUpdated(raw: unknown): string {
  return raw instanceof Date ? raw.toISOString().slice(0, 10) : String(raw ?? '');
}

// Kebab-slug gate. Single source so the prerender/sitemap slug set
// (getAllGuideSlugs) and the render gate (fileExists/getGuideBySlug) agree on
// what's valid — a non-kebab filename must not be advertised then 404.
const SLUG_PATTERN = /^[a-z0-9-]+$/;

function fileExists(slug: string): boolean {
  return SLUG_PATTERN.test(slug) && fs.existsSync(path.join(GUIDES_DIR, `${slug}.mdx`));
}

export function getAllGuideSlugs(): { slug: string }[] {
  if (!fs.existsSync(GUIDES_DIR)) return [];
  return fs
    .readdirSync(GUIDES_DIR)
    .filter((f) => f.endsWith('.mdx'))
    .map((f) => f.replace(/\.mdx$/, ''))
    // Parity with fileExists: a slug getGuideBySlug would notFound() must not
    // enter generateStaticParams or the sitemap (would advertise a 404).
    .filter((slug) => SLUG_PATTERN.test(slug))
    .map((slug) => ({ slug }));
}

export function getGuideBySlug(slug: string): Guide | null {
  if (!fileExists(slug)) return null;
  const raw = fs.readFileSync(path.join(GUIDES_DIR, `${slug}.mdx`), 'utf8');
  const { data, content } = matter(raw);
  // Slug is filename-derived (authoritative) regardless of any frontmatter slug —
  // the URL can't drift from the file.
  const frontmatter: GuideFrontmatter = {
    slug,
    kind: String(data.kind ?? 'GUIDE'),
    updated: normalizeUpdated(data.updated),
    title: String(data.title ?? slug),
    ...(data.description ? { description: String(data.description) } : {}),
  };
  return { frontmatter, body: content };
}

// All guides as full objects, newest-revised first — the canonical full-list
// accessor (getAllGuideSlugs is the slug-only sibling for generateStaticParams /
// sitemap). Drops any slug whose file fails the gate (getGuideBySlug → null) so a
// malformed .mdx can't crash a list consumer. Sort is by the YYYY-MM-DD `updated`
// string (lexical == chronological for ISO dates, tz-independent).
export function getAllGuides(): Guide[] {
  return getAllGuideSlugs()
    .map(({ slug }) => getGuideBySlug(slug))
    .filter((g): g is Guide => g !== null)
    .sort((a, b) => b.frontmatter.updated.localeCompare(a.frontmatter.updated));
}

// Matches the two MDX coral-citation components — <CoralEntry slug="…"> and
// <CoralReference slug="…"> — capturing the slug. Component tags ONLY: a bare
// /coral/… prose link (e.g. the price-history mention) is deliberately not a
// "featured" signal. Featuring is the editorial act of giving a coral its own
// entry/market line, not naming its URL in passing — so a coral linked only in
// prose earns no back-link. [^>]* keeps the match inside the opening tag, and the
// slug attribute can sit anywhere among the tag's attributes.
const FEATURED_CORAL_RE = /<Coral(?:Entry|Reference)\b[^>]*?\bslug="([^"]+)"/g;

// The distinct coral slugs a guide body features via component tags. Set dedups
// the same coral cited as both a <CoralEntry> and a <CoralReference> (or twice).
function featuredCoralSlugs(body: string): Set<string> {
  const slugs = new Set<string>();
  for (const match of body.matchAll(FEATURED_CORAL_RE)) {
    // Capture group 1 always present when the pattern matches; the guard is for
    // TS strict (RegExp groups type as string | undefined).
    if (match[1]) slugs.add(match[1]);
  }
  return slugs;
}

// Guides whose body features the given coral via a <CoralEntry>/<CoralReference>
// component — the reverse index behind the /coral/[slug] "Featured in:" back-link.
// Derived from the MDX at read-time, never a hand-kept map: add a coral to a guide
// and its coral page links back with no second edit. Order follows getAllGuides
// (newest-revised first). Empty array when no guide features the coral.
export function getGuidesFeaturingCoral(coralSlug: string): Guide[] {
  return getAllGuides().filter((guide) =>
    featuredCoralSlugs(guide.body).has(coralSlug),
  );
}
