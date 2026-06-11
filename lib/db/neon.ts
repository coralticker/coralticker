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
// missing via getRequiredEnv (this file was the idiom's donor; extracted at
// CTK-128 (f)). Server-only by CONVENTION — nothing mechanical excludes
// this module from a client bundle; if its import graph ever nears one,
// add the `server-only` marker package (build-time error) rather than
// trusting where the env read happens.
//
// @neondatabase/serverless ships a fetch-compatible HTTP driver — no pooler
// ceremony, native to Vercel's edge/serverless runtime. The tagged-template
// `sql` returned by `neon()` parameterizes ${...} interpolations safely
// (each becomes $N + values array under the hood).

import { neon, type NeonQueryFunction } from '@neondatabase/serverless';
// Relative + extensioned, NOT '@/lib/env': this file is dynamically imported
// by bare-node entrypoints (scripts/discord-digest.ts fetchRows → the 13:00
// UTC cron workflow; scripts/send_test_digest.ts live path), and node
// --experimental-strip-types resolves no tsconfig path aliases — an '@/'
// specifier here crashes the digest cron with ERR_MODULE_NOT_FOUND (caught
// at CTK-128 close /code-review).
import { getRequiredEnv } from '../env.ts';

const NEON_DATABASE_URL = getRequiredEnv('NEON_DATABASE_URL');

let _sql: NeonQueryFunction<false, false> | null = null;

export function getNeonSql(): NeonQueryFunction<false, false> {
  if (_sql === null) {
    _sql = neon(NEON_DATABASE_URL);
  }
  return _sql;
}
