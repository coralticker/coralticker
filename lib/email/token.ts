// The two token encodings differ (base64url from generate() vs. the
// gen_random_uuid()::text DB default that backfills existing rows) but both are
// opaque and URL-safe — the token is never parsed, only matched.
//
// Email links must be absolute — there's no relative base in an inbox — and
// point at the canonical apex coralticker.com, mirroring app/layout.tsx
// metadataBase. send.coralticker.com is the mail envelope only; it is never a
// link target.

import { randomBytes } from 'node:crypto';

// Canonical public origin. The apex hosts the /confirm + /unsubscribe routes.
const SITE_ORIGIN = 'https://coralticker.com';

// 32 random bytes, base64url-encoded: URL-safe charset ([A-Za-z0-9_-], no
// padding), so it drops straight into a ?t= param with no escaping.
export function generate(): string {
  return randomBytes(32).toString('base64url');
}

// encodeURIComponent is a no-op for base64url ([A-Za-z0-9_-]) and the uuid
// DB-default ([0-9a-f-]) — both are URL-safe — but it's defense-in-depth: any
// future token shape can't break out of the query param or the email href.
export function confirmUrl(token: string): string {
  return `${SITE_ORIGIN}/confirm?t=${encodeURIComponent(token)}`;
}

export function unsubscribeUrl(token: string): string {
  return `${SITE_ORIGIN}/unsubscribe?t=${encodeURIComponent(token)}`;
}
