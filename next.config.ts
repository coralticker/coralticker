import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // The /guides pages read content/guides/*.mdx via fs at request/build time;
  // trace those files into the serverless bundle so the read resolves on Vercel,
  // not just locally. /coral/[slug] reads the same dir via getGuidesFeaturingCoral
  // (the "Featured in:" back-link reverse index, CTK-184 part b) — without its own
  // trace entry the .mdx files are absent from that function on Vercel, fs returns
  // an empty dir, and the back-links silently never render in prod.
  outputFileTracingIncludes: {
    '/guides/[slug]': ['./content/guides/**/*'],
    '/coral/[slug]': ['./content/guides/**/*'],
    '/sitemap.xml': ['./content/guides/**/*'],
  },
};

export default nextConfig;
