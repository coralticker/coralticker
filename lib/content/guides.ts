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

// "2026-06-21" → "JUN 2026". Absolute month-year, never relative (D-4: relative
// time implies an auto-freshness the editorial layer doesn't have). String split
// (not Date) so it's tz-independent.
export function updatedMonthYear(updated: string): string {
  const [year, month] = updated.split('-');
  const m = Number(month);
  const name = m >= 1 && m <= 12 ? MONTHS[m - 1] : '';
  return name ? `${name} ${year}` : String(year ?? updated);
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
    updated: String(data.updated ?? ''),
    title: String(data.title ?? slug),
    ...(data.description ? { description: String(data.description) } : {}),
  };
  return { frontmatter, body: content };
}
