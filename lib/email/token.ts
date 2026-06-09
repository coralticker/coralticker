// lib/email/token.ts
//
// Per-row opaque token (CTK-016 D-1) + the confirm / unsubscribe URL builders.
//
// generate() mints the app-side value Leg 3 writes at signup-insert:
// crypto.randomBytes(32).toString('base64url'). The 0037 migration's
// gen_random_uuid()::text DB default backfills existing rows and covers the
// apply->Leg-3 deploy gap; that default is RETAINED as the live-path safety net
// (see CTK-016 results, Leg 1). The two encodings differ (base64url vs. UUID)
// but both are opaque and both are URL-safe — the token is never parsed, only
// matched.
//
// One token per row serves BOTH routes; the route scopes the purpose (/confirm
// sets confirmed_at, /unsubscribe sets unsubscribed_at). Email links must be
// absolute — there's no relative base in an inbox — and point at the canonical
// apex coralticker.com, mirroring app/layout.tsx metadataBase (the site's
// single source of truth for its public origin). send.coralticker.com (D-2) is
// the mail envelope only; it is never a link target. The /confirm and
// /unsubscribe routes themselves land in Leg 4.

import { randomBytes } from 'node:crypto';

// Canonical public origin. Mirrors app/layout.tsx:16 metadataBase. The apex
// hosts the /confirm + /unsubscribe routes.
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
