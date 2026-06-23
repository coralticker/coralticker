import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import { MDXRemote } from 'next-mdx-remote/rsc';
import {
  getAllGuideSlugs,
  getGuideBySlug,
  stripTrailingPeriod,
  updatedMonthYear,
} from '@/lib/content/guides';
import { buildGuideJsonLd } from '@/lib/seo/guide-jsonld';
import { serializeJsonLd } from '@/lib/seo/coral-jsonld';
import { SITE_URL } from '@/lib/seo/site-url';
import { PageShell } from '@/components/ui/page-shell';
import { PageEyebrow } from '@/components/ui/page-eyebrow';
import { PageH1 } from '@/components/ui/page-h1';
import { mdxComponents } from './_mdx-components';

// ISR: guide prose is static (the .mdx file), but the embedded <CoralReference>
// market lines pull live price data behind their own 300s unstable_cache windows
// — so the page revalidates on the same cadence as that data.
export const revalidate = 300;

export async function generateStaticParams(): Promise<{ slug: string }[]> {
  return getAllGuideSlugs();
}

// Trailing period stripped for the SERP <title> so the root "%s — CoralTicker"
// template's em-dash is the only separator (the on-page H1 keeps the declarative
// period per casing canon).
function metaTitle(title: string): string {
  return stripTrailingPeriod(title);
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  const guide = getGuideBySlug(slug);
  if (!guide) return { title: 'Guide not found' };

  const { title, description } = guide.frontmatter;
  return {
    title: metaTitle(title),
    description: description ?? `${metaTitle(title)} — a CoralTicker buying guide.`,
    alternates: { canonical: `/guides/${slug}` },
    openGraph: {
      url: `/guides/${slug}`,
      siteName: 'CoralTicker',
      type: 'article',
      locale: 'en_US',
    },
    twitter: { card: 'summary' },
  };
}

export default async function GuidePage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const guide = getGuideBySlug(slug);
  if (!guide) notFound();

  const { kind, updated, title, description } = guide.frontmatter;
  const jsonLd = buildGuideJsonLd({
    siteUrl: SITE_URL,
    slug,
    title,
    description: description ?? null,
    updated,
  });

  return (
    <PageShell as="article">
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: serializeJsonLd(jsonLd) }}
      />
      <PageEyebrow chunks={[kind, ...(updated ? [`UPDATED ${updatedMonthYear(updated)}`] : [])]} />
      <PageH1 className="mb-6">{title}</PageH1>
      <MDXRemote source={guide.body} components={mdxComponents} />
    </PageShell>
  );
}
