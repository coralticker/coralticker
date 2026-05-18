// lib/db/neon.ts
//
// Server-side Neon client wrapper. Read-path for Server Components; write-path
// (signup INSERT/SELECT/UPDATE) routes through this same client in Server
// Actions. Replaces lib/supabase/server.ts at CTK-043 cut-4 (2026-05-16) —
// architecture-v1.md §1 decision register #65 names Neon as the v1 DB stack.
//
// Uses NEON_DATABASE_URL — a direct Postgres connection string from the Neon
// dashboard. No RLS layer; Neon is bare Postgres, so the service-role-bypass
// posture from Supabase no longer applies. Module-scope read with throw-on-
// missing; the file lives outside the client bundle by virtue of consuming
// `process.env` at module scope.
//
// @neondatabase/serverless ships a fetch-compatible HTTP driver — no pooler
// ceremony, native to Vercel's edge/serverless runtime. The tagged-template
// `sql` returned by `neon()` parameterizes ${...} interpolations safely
// (each becomes $N + values array under the hood).

import { neon, type NeonQueryFunction } from '@neondatabase/serverless';

const NEON_DATABASE_URL = process.env.NEON_DATABASE_URL;

if (!NEON_DATABASE_URL) {
  throw new Error('NEON_DATABASE_URL must be set. See .env.example.');
}

let _sql: NeonQueryFunction<false, false> | null = null;

export function getNeonSql(): NeonQueryFunction<false, false> {
  if (_sql === null) {
    _sql = neon(NEON_DATABASE_URL!);
  }
  return _sql;
}
