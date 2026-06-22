import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // The /guides pages read content/guides/*.mdx via fs at request/build time;
  // trace those files into the serverless bundle so the read resolves on Vercel,
  // not just locally.
  outputFileTracingIncludes: {
    '/guides/[slug]': ['./content/guides/**/*'],
    '/sitemap.xml': ['./content/guides/**/*'],
  },
};

export default nextConfig;
