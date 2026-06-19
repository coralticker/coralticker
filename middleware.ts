import { NextResponse, type NextRequest } from 'next/server';
import { isReferrerChannel } from '@/types/email-signups';

// First-touch channel attribution. A ?ref= on any entry route is stamped into an
// httpOnly cookie the signup Server Action reads later — middleware is the only
// Next 15 surface that can set a cookie on an arbitrary route (Server Components
// can't, and we don't want a ?ref= to require a write-capable route to land).
//
// First-touch WINS: an existing ct_ref is never overwritten, so the channel that
// first brought someone here survives later visits with a different (or no) ?ref=.

const REF_COOKIE = 'ct_ref';
const REF_MAX_AGE_SECONDS = 60 * 60 * 24 * 90; // ~90 days

export function middleware(request: NextRequest) {
  const response = NextResponse.next();

  if (request.cookies.has(REF_COOKIE)) {
    return response;
  }

  // Normalize at this entry boundary only — isReferrerChannel stays a pure
  // exact-match guard. A mis-cased campaign link (?ref=IG) then still lands the
  // channel, and both the stored cookie and the action's read see the canonical form.
  const ref = request.nextUrl.searchParams.get('ref')?.toLowerCase().trim() ?? null;
  if (isReferrerChannel(ref)) {
    response.cookies.set(REF_COOKIE, ref, {
      httpOnly: true,
      sameSite: 'lax',
      path: '/',
      // Production-only so LAN/IP HTTP previews can still set the cookie; localhost
      // is already a secure context, so dev is unaffected.
      secure: process.env.NODE_ENV === 'production',
      maxAge: REF_MAX_AGE_SECONDS,
    });
  }

  return response;
}

export const config = {
  // Skip Next internals + any path with a file extension (static assets,
  // favicon, robots.txt) — they never carry the entry ?ref=.
  matcher: ['/((?!_next/static|_next/image|favicon.ico|.*\\..*).*)'],
};
